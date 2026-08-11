from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from gapsim import updater
from gapsim.emulation.data_paths import paths_for_data_root


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._stream = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


class UpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.company = updater.COMPANY_CHANNEL
        self.release = {
            "tag_name": "0.1.1",
            "published_at": "2026-07-23T00:00:00Z",
            "body": "Release notes",
            "assets": [
                {"name": "Gapseam.zip", "browser_download_url": "https://company/Gapseam.zip", "size": 12},
                {"name": "version.json", "browser_download_url": "https://company/version.json"},
            ],
        }

    def test_company_release_manager_manifest_is_parsed(self) -> None:
        manifest = {
            "version": "0.1.1",
            "asset": "Gapseam.zip",
            "downloadUrl": "https://company/download/Gapseam.zip",
            "sha256": "abc",
            "notes": "Fixed updater",
            "publishedAtUtc": "2026-07-23T00:00:00Z",
        }
        info = updater._update_info_from_release(self.company, self.release, manifest)
        self.assertEqual(info.latest_version, "0.1.1")
        self.assertEqual(info.asset, "Gapseam.zip")
        self.assertEqual(info.download_url, manifest["downloadUrl"])
        self.assertEqual(info.sha256, "abc")
        self.assertEqual(info.notes, "Fixed updater")
        self.assertEqual(info.latest_build_date, manifest["publishedAtUtc"])

    def test_latest_api_response_loads_manifest_asset(self) -> None:
        manifest = {"version": "0.1.1", "downloadUrl": "https://company/Gapseam.zip"}

        def fake_read(url: str, timeout: int) -> dict:
            return self.release if url == self.company.release_api_url else manifest

        with patch.object(updater, "_read_json", side_effect=fake_read):
            info = updater._fetch_update_info_from_api(self.company)
        self.assertEqual(info.latest_version, "0.1.1")
        self.assertEqual(info.download_url, "https://company/Gapseam.zip")

    def test_version_and_notes_display_fields(self) -> None:
        info = updater.UpdateInfo("0.1.0", "local", "", "0.1.2", "build-7", "", "", "", "", notes="Line 1")
        self.assertTrue(info.is_available)
        self.assertEqual(info.current_label, "0.1.0")
        self.assertEqual(info.latest_label, "0.1.2 (build-7)")
        self.assertEqual(info.notes, "Line 1")

    def test_same_company_version_detects_new_company_build_id(self) -> None:
        info = updater.UpdateInfo(
            "0.1.1", "company-old", "", "0.1.1", "company-new", "", "", "", "",
            channel="company", build_id_updates=True,
        )
        self.assertTrue(info.is_available)

    def test_company_channel_uses_actual_enterprise_repository(self) -> None:
        self.assertEqual(
            updater.COMPANY_CHANNEL.release_api_url,
            "http://github.samsungds.net/api/v3/repos/bh2-min/Gapseam/releases/latest",
        )
        self.assertEqual(
            updater.COMPANY_CHANNEL.release_page_url,
            "http://github.samsungds.net/bh2-min/Gapseam/releases",
        )

    def test_sha256_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bad.zip"
            with patch.object(updater.urllib.request, "urlopen", return_value=_FakeResponse(b"not a zip")):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    updater._download_file(
                        "https://company/Gapseam.zip",
                        target,
                        "0" * 64,
                        0,
                        progress=None,
                        timeout=1,
                    )
            self.assertFalse(target.exists())

    def test_zip_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "bad.zip"
            zip_path.write_bytes(_zip_bytes({"../evil.txt": b"no"}))
            with self.assertRaisesRegex(RuntimeError, "안전하지 않은 경로"):
                updater.stage_update_zip(zip_path, Path(tmp) / "stage")

    def test_staging_folder_requires_gfe_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "good.zip"
            zip_path.write_bytes(_zip_bytes({"GFE/GFE.exe": b"exe", "GFE/_internal/module.py": b"py"}))
            staged_root = updater.stage_update_zip(zip_path, Path(tmp) / "stage")
            self.assertEqual(staged_root.name, "GFE")
            self.assertTrue((staged_root / "GFE.exe").is_file())

            bad_zip = Path(tmp) / "missing.zip"
            bad_zip.write_bytes(_zip_bytes({"GFE/readme.txt": b"missing"}))
            with self.assertRaisesRegex(RuntimeError, "GFE.exe"):
                updater.stage_update_zip(bad_zip, Path(tmp) / "missing-stage")

    def test_update_script_rolls_back_and_does_not_reference_user_data_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(updater, "update_work_dir", return_value=Path(tmp) / "work"):
            install = Path(tmp) / "GFE"
            staged = Path(tmp) / "staged" / "GFE"
            install.mkdir()
            staged.mkdir(parents=True)
            (install / "GFE.exe").write_bytes(b"old")
            (staged / "GFE.exe").write_bytes(b"new")
            script = updater._write_update_script(install / "GFE.exe", staged, 12345)
            text = script.read_text(encoding="utf-8-sig")
            self.assertIn("backupRoot", text)
            self.assertIn("Move-Item -LiteralPath $backupRoot -Destination $installRoot", text)
            self.assertNotIn("GapseamData", text)
            self.assertNotIn("data_root.json", text)
            self.assertNotIn("addons_state.json", text)

    def test_user_data_paths_are_outside_install_root(self) -> None:
        paths = paths_for_data_root(Path.home() / "Documents" / "GapseamData")
        self.assertIn("GapseamData", str(paths.root))
        self.assertNotIn("GFE", str(paths.root))
        self.assertEqual(paths.addon_state_path.name, "addons_state.json")

    def test_source_execution_cannot_replace_installation(self) -> None:
        with patch.object(updater, "is_packaged_app", return_value=False):
            self.assertIn("소스 실행", updater.update_install_error())
            with self.assertRaisesRegex(RuntimeError, "소스 실행"):
                updater.launch_self_update(Path("unused"))

    def test_401_and_403_are_clear_enterprise_errors(self) -> None:
        for status in (401, 403):
            error = urllib.error.HTTPError("https://company", status, "Denied", {}, None)
            with patch.object(updater.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(updater.UpdateAuthenticationError) as raised:
                    updater._read_url_bytes("https://company", 1)
            self.assertIn("토큰을 요구하지 말고", str(raised.exception))

    def test_write_permission_error_is_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "open", side_effect=PermissionError("denied")):
            message = updater.update_install_error(Path(tmp) / "GFE.exe")
        self.assertIn("쓸 권한이 없습니다", message)
        self.assertIn("denied", message)

    def test_company_channel_can_be_selected_from_embedded_build_info(self) -> None:
        with patch.object(updater, "UPDATE_CHANNEL", "company"):
            self.assertEqual(updater.selected_channel(), updater.COMPANY_CHANNEL)

    def test_build_script_embeds_company_channel_and_fixed_zip_name(self) -> None:
        script = Path(__file__).resolve().parents[1] / "build-company-release.ps1"
        text = script.read_text(encoding="utf-8")
        self.assertIn('UPDATE_CHANNEL = "company"', text)
        self.assertIn("GFE.spec", text)
        self.assertIn("Gapseam.zip", text)
        self.assertIn("--build-info-json", text)
        self.assertIn("Remove-BuildInfoBytecode", text)

    def test_download_update_stages_verified_zip(self) -> None:
        payload = _zip_bytes({"GFE/GFE.exe": b"exe"})
        digest = hashlib.sha256(payload).hexdigest()
        info = updater.UpdateInfo("0.1.0", "", "", "0.1.1", "", "", "", "", "https://company/Gapseam.zip", sha256=digest)
        with tempfile.TemporaryDirectory() as tmp, patch.object(updater, "update_work_dir", return_value=Path(tmp)), patch.object(
            updater.urllib.request,
            "urlopen",
            return_value=_FakeResponse(payload),
        ):
            staged = updater.download_update(info)
            self.assertEqual(staged.name, "GFE")
            self.assertTrue((staged / "GFE.exe").is_file())


if __name__ == "__main__":
    unittest.main()
