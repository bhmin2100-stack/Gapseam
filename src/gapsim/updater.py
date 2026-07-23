from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable, Optional

from . import __version__

try:
    from .build_info import APP_VERSION, BUILD_COMMIT, BUILD_DATE, BUILD_ID, UPDATE_CHANNEL
except Exception:  # pragma: no cover - source-tree fallback
    APP_VERSION = __version__
    BUILD_COMMIT = "local"
    BUILD_DATE = ""
    BUILD_ID = "local"
    UPDATE_CHANNEL = "personal"


ZIP_ASSET_NAME = "Gapseam.zip"
VERSION_ASSET_NAME = "version.json"
APP_EXE_NAME = "GFE.exe"
APP_FOLDER_NAME = "GFE"
PERSONAL_RELEASE_API_URL = "https://api.github.com/repos/bhmin2100-stack/Gapseam/releases/latest"
PERSONAL_RELEASE_PAGE_URL = "https://github.com/bhmin2100-stack/Gapseam/releases"
COMPANY_RELEASE_API_URL = "https://github.samsungds.net/api/v3/repos/bh2-min/Gapseam/releases/latest"
COMPANY_RELEASE_PAGE_URL = "https://github.samsungds.net/bh2-min/Gapseam/releases"
USER_AGENT = f"Gapseam-GFE/{__version__}"


class UpdateAuthenticationError(RuntimeError):
    """The Enterprise release cannot be read by this user or network session."""


@dataclass(frozen=True)
class UpdateChannel:
    name: str
    release_api_url: str
    release_page_url: str


PERSONAL_CHANNEL = UpdateChannel("personal", PERSONAL_RELEASE_API_URL, PERSONAL_RELEASE_PAGE_URL)
COMPANY_CHANNEL = UpdateChannel("company", COMPANY_RELEASE_API_URL, COMPANY_RELEASE_PAGE_URL)


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    current_build_id: str
    current_commit: str
    latest_version: str
    latest_build_id: str
    latest_commit: str
    latest_build_date: str
    release_url: str
    download_url: str
    asset: str = ZIP_ASSET_NAME
    sha256: str = ""
    size: int = 0
    notes: str = ""
    channel: str = "personal"

    @property
    def is_available(self) -> bool:
        return compare_versions(self.latest_version, self.current_version) > 0

    @property
    def current_label(self) -> str:
        if self.current_build_id and self.current_build_id != "local":
            return f"{self.current_version} ({self.current_build_id})"
        return self.current_version

    @property
    def latest_label(self) -> str:
        if self.latest_build_id:
            return f"{self.latest_version} ({self.latest_build_id})"
        return self.latest_version


def selected_channel() -> UpdateChannel:
    return COMPANY_CHANNEL if str(UPDATE_CHANNEL).strip().lower() == "company" else PERSONAL_CHANNEL


def is_packaged_app() -> bool:
    return bool(getattr(sys, "frozen", False)) and Path(sys.executable).name.lower() == APP_EXE_NAME.lower()


def current_version() -> str:
    return str(APP_VERSION or __version__)


def current_build_id() -> str:
    return str(BUILD_ID or "local")


def compare_versions(left: str, right: str) -> int:
    left_parts = _version_parts(left)
    right_parts = _version_parts(right)
    max_len = max(len(left_parts), len(right_parts), 1)
    left_parts += [0] * (max_len - len(left_parts))
    right_parts += [0] * (max_len - len(right_parts))
    return (left_parts > right_parts) - (left_parts < right_parts)


def fetch_update_info(timeout: int = 10) -> UpdateInfo:
    channel = selected_channel()
    try:
        return _fetch_update_info_from_api(channel, timeout=timeout)
    except UpdateAuthenticationError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "업데이트 정보를 확인하지 못했습니다.\n"
            f"- 배포 채널: {channel.name}\n"
            f"- API: {channel.release_api_url}\n"
            f"- 원인: {exc}\n"
            f"- 확인 URL: {channel.release_page_url}"
        ) from exc


def _fetch_update_info_from_api(channel: UpdateChannel, timeout: int = 10) -> UpdateInfo:
    release = _read_json(channel.release_api_url, timeout=timeout)
    assets = release.get("assets") or []
    manifest_asset = _find_asset(assets, VERSION_ASSET_NAME)
    if channel.name == COMPANY_CHANNEL.name and not manifest_asset:
        raise RuntimeError(f"{VERSION_ASSET_NAME} release asset not found.")
    manifest = _read_json(str(manifest_asset.get("browser_download_url") or ""), timeout=timeout) if manifest_asset else {}
    return _update_info_from_release(channel, release, manifest)


def _update_info_from_release(channel: UpdateChannel, release: dict, manifest: dict) -> UpdateInfo:
    asset_name = str(manifest.get("asset") or ZIP_ASSET_NAME)
    assets = release.get("assets") or []
    zip_asset = _find_asset(assets, asset_name)
    download_url = str(manifest.get("downloadUrl") or (zip_asset or {}).get("browser_download_url") or "")
    if not download_url:
        raise RuntimeError(f"{asset_name} release asset not found.")
    latest_version = str(manifest.get("version") or release.get("tag_name") or "")
    if not latest_version:
        raise RuntimeError("Release metadata did not contain a version.")
    return UpdateInfo(
        current_version=current_version(),
        current_build_id=current_build_id(),
        current_commit=str(BUILD_COMMIT or ""),
        latest_version=latest_version,
        latest_build_id=str(manifest.get("build_id") or release.get("target_commitish") or ""),
        latest_commit=str(manifest.get("commit") or ""),
        latest_build_date=str(manifest.get("publishedAtUtc") or manifest.get("build_date") or release.get("published_at") or ""),
        release_url=str(release.get("html_url") or channel.release_page_url),
        download_url=download_url,
        asset=asset_name,
        sha256=str(manifest.get("sha256") or ""),
        size=int(manifest.get("size") or (zip_asset or {}).get("size") or 0),
        notes=str(manifest.get("notes") or release.get("body") or "").strip(),
        channel=channel.name,
    )


def download_update(
    info: UpdateInfo,
    progress: Optional[Callable[[int, int], None]] = None,
    timeout: int = 60,
) -> Path:
    update_dir = update_work_dir()
    package_dir = update_dir / f"package-{_safe_name(info.latest_version)}"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    zip_path = package_dir / _safe_zip_name(info.asset)
    _download_file(info.download_url, zip_path, info.sha256, info.size, progress=progress, timeout=timeout)
    staging_dir = stage_update_zip(zip_path, package_dir / "staged")
    return staging_dir


def stage_update_zip(zip_path: Path, staging_dir: Path) -> Path:
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        _safe_extract_zip(archive, staging_dir)
    return validate_staged_package(staging_dir)


def validate_staged_package(staging_dir: Path) -> Path:
    candidates = [staging_dir / APP_FOLDER_NAME, staging_dir]
    for candidate in candidates:
        exe = candidate / APP_EXE_NAME
        if exe.is_file() and any(candidate.iterdir()):
            return candidate.resolve()
    raise RuntimeError(f"업데이트 ZIP에 {APP_FOLDER_NAME}\\{APP_EXE_NAME} 또는 {APP_EXE_NAME}가 없습니다.")


def update_install_error(current_exe: Optional[Path] = None) -> str:
    if not is_packaged_app() and current_exe is None:
        return "소스 실행 상태에서는 자동 교체를 수행하지 않습니다. 배포된 GFE.exe에서만 업데이트할 수 있습니다."
    install_root = install_root_for_exe(current_exe or Path(sys.executable))
    probe = install_root / f".gapseam_update_write_test_{os.getpid()}"
    try:
        with probe.open("xb"):
            pass
        probe.unlink()
    except (OSError, PermissionError) as exc:
        return (
            f"설치 폴더에 업데이트 파일을 쓸 권한이 없습니다.\n{install_root}\n\n"
            "쓰기 가능한 폴더에 GFE 폴더를 옮긴 뒤 다시 실행하거나 관리자에게 권한을 요청하세요.\n"
            f"원인: {exc}"
        )
    return ""


def launch_self_update(staged_install_root: Path) -> None:
    if not is_packaged_app():
        raise RuntimeError("소스 실행 상태에서는 자동 교체를 수행하지 않습니다. 배포된 GFE.exe에서만 업데이트할 수 있습니다.")
    current_exe = Path(sys.executable).resolve()
    if error := update_install_error(current_exe):
        raise RuntimeError(error)
    staged_root = validate_staged_package(Path(staged_install_root))
    script = _write_update_script(current_exe=current_exe, staged_root=staged_root, pid=os.getpid())
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        close_fds=True,
        creationflags=creationflags,
    )


def install_root_for_exe(executable: Path) -> Path:
    exe = Path(executable).resolve()
    return exe.parent


def update_work_dir() -> Path:
    return Path(tempfile.gettempdir()) / "gapseam_update"


def _download_file(
    url: str,
    target: Path,
    expected_sha256: str,
    expected_size: int,
    *,
    progress: Optional[Callable[[int, int], None]],
    timeout: int,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    downloaded = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or expected_size or 0)
            with target.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total)
    except Exception as urllib_error:
        target.unlink(missing_ok=True)
        try:
            _download_file_with_powershell(url, target, timeout=timeout)
        except Exception as ps_error:
            raise RuntimeError(f"업데이트 ZIP 다운로드 실패: urllib={urllib_error}; PowerShell={ps_error}") from ps_error
        downloaded = target.stat().st_size
        hasher = hashlib.sha256(target.read_bytes())
        if progress:
            progress(downloaded, expected_size or downloaded)
    actual = hasher.hexdigest().lower()
    if expected_sha256 and actual != expected_sha256.lower():
        target.unlink(missing_ok=True)
        raise RuntimeError("다운로드한 업데이트 ZIP의 SHA-256 검증에 실패했습니다.")


def _safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.infolist():
        normalized = member.filename.replace("\\", "/")
        pure = PurePosixPath(normalized)
        if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
            raise RuntimeError(f"업데이트 ZIP에 안전하지 않은 경로가 있습니다: {member.filename}")
        target = (destination / Path(*pure.parts)).resolve()
        if target != destination and destination not in target.parents:
            raise RuntimeError(f"업데이트 ZIP 경로가 staging 폴더 밖을 가리킵니다: {member.filename}")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, target.open("wb") as sink:
            shutil.copyfileobj(source, sink)


def _read_json(url: str, timeout: int) -> dict:
    if not url:
        return {}
    return json.loads(_read_url_bytes(url, timeout=timeout).decode("utf-8-sig"))


def _read_url_bytes(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise UpdateAuthenticationError(
                "회사 GitHub Enterprise Release를 읽을 권한이 없습니다. "
                "사용자에게 토큰을 요구하지 말고, 배포 관리자에게 Release 읽기 권한을 요청하세요."
            ) from error
        raise RuntimeError(f"HTTP {error.code}: {error.reason}") from error
    except Exception as urllib_error:
        if os.name != "nt":
            raise
        try:
            return _read_url_with_powershell(url, timeout=timeout)
        except Exception as ps_error:
            raise RuntimeError(f"서버에 연결하지 못했습니다. urllib={urllib_error}; PowerShell={ps_error}") from ps_error


def _read_url_with_powershell(url: str, timeout: int) -> bytes:
    command = (
        "$ProgressPreference = 'SilentlyContinue'; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
        f"$response = Invoke-WebRequest -Uri {_ps_quote(url)} -UseBasicParsing -TimeoutSec {max(1, timeout)}; "
        "$content = $response.Content; $bytes = if ($content -is [byte[]]) { $content } else { [System.Text.Encoding]::UTF8.GetBytes([string]$content) }; "
        "[Console]::Out.Write([Convert]::ToBase64String($bytes))"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        timeout=timeout + 15,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        if "401" in stderr or "403" in stderr:
            raise UpdateAuthenticationError(
                "회사 GitHub Enterprise Release를 읽을 권한이 없습니다. "
                "사용자에게 토큰을 요구하지 말고, 배포 관리자에게 Release 읽기 권한을 요청하세요."
            )
        raise RuntimeError(stderr or f"PowerShell exited with {completed.returncode}")
    return base64.b64decode(completed.stdout.strip())


def _download_file_with_powershell(url: str, target: Path, timeout: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    command = (
        "$ProgressPreference = 'SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
        f"Invoke-WebRequest -Uri {_ps_quote(url)} -OutFile {_ps_quote(target)} -UseBasicParsing -TimeoutSec {max(1, timeout)}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        timeout=timeout + 60,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(stderr or f"PowerShell exited with {completed.returncode}")
    if not target.exists() or target.stat().st_size <= 0:
        raise RuntimeError("PowerShell did not create a valid download file.")


def _find_asset(assets: list[dict], name: str) -> Optional[dict]:
    return next((asset for asset in assets if asset.get("name") == name), None)


def _version_parts(value: str) -> list[int]:
    return [int(part) for part in re.findall(r"\d+", value)]


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "Gapseam"


def _safe_zip_name(value: str) -> str:
    name = Path(str(value or ZIP_ASSET_NAME)).name
    return name if name.lower().endswith(".zip") else ZIP_ASSET_NAME


def _ps_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _write_update_script(current_exe: Path, staged_root: Path, pid: int) -> Path:
    update_dir = update_work_dir()
    update_dir.mkdir(parents=True, exist_ok=True)
    install_root = install_root_for_exe(current_exe)
    parent_dir = install_root.parent
    backup_root = parent_dir / f"{install_root.name}.backup-{int(time.time())}"
    script = update_dir / f"gapseam_update_{pid}.ps1"
    log_path = update_dir / "gapseam_update.log"
    script.write_text(
        f"""
$ErrorActionPreference = 'Stop'
$installRoot = {_ps_quote(install_root)}
$newRoot = {_ps_quote(staged_root)}
$backupRoot = {_ps_quote(backup_root)}
$parentDir = {_ps_quote(parent_dir)}
$targetExe = Join-Path $installRoot {APP_EXE_NAME!r}
$newExe = Join-Path $newRoot {APP_EXE_NAME!r}
$logPath = {_ps_quote(log_path)}
$pidToWait = {pid}
function Move-WithRetry($source, $destination) {{
    for ($i = 0; $i -lt 60; $i++) {{
        try {{ Move-Item -LiteralPath $source -Destination $destination -Force; return }} catch {{ Start-Sleep -Milliseconds 500 }}
    }}
    Move-Item -LiteralPath $source -Destination $destination -Force
}}
try {{
    Wait-Process -Id $pidToWait -Timeout 60 -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300
    if (-not (Test-Path -LiteralPath $newExe)) {{ throw "Staged GFE.exe not found: $newExe" }}
    if (Test-Path -LiteralPath $backupRoot) {{ Remove-Item -LiteralPath $backupRoot -Recurse -Force -ErrorAction SilentlyContinue }}
    if (Test-Path -LiteralPath $installRoot) {{ Move-WithRetry $installRoot $backupRoot }}
    try {{
        Move-WithRetry $newRoot $installRoot
    }} catch {{
        if ((Test-Path -LiteralPath $backupRoot) -and -not (Test-Path -LiteralPath $installRoot)) {{
            Move-Item -LiteralPath $backupRoot -Destination $installRoot -Force
        }}
        throw
    }}
    if (-not (Test-Path -LiteralPath $targetExe)) {{
        if ((Test-Path -LiteralPath $backupRoot) -and -not (Test-Path -LiteralPath $installRoot)) {{
            Move-Item -LiteralPath $backupRoot -Destination $installRoot -Force
        }}
        throw "Updated GFE.exe not found: $targetExe"
    }}
    Start-Process -FilePath $targetExe -WorkingDirectory $installRoot
    Start-Sleep -Seconds 2
    if (Test-Path -LiteralPath $backupRoot) {{ Remove-Item -LiteralPath $backupRoot -Recurse -Force -ErrorAction SilentlyContinue }}
}} catch {{
    $_ | Out-File -FilePath $logPath -Encoding UTF8
    try {{
        if ((Test-Path -LiteralPath $backupRoot) -and -not (Test-Path -LiteralPath $installRoot)) {{
            Move-Item -LiteralPath $backupRoot -Destination $installRoot -Force
        }}
    }} catch {{ $_ | Out-File -FilePath $logPath -Encoding UTF8 -Append }}
    exit 1
}} finally {{
    Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
}}
""".lstrip(),
        encoding="utf-8-sig",
    )
    return script
