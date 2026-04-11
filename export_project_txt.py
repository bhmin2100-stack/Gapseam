from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent
EXPORT_ROOT = ROOT / "exports"

# Directories to skip completely.
# `runs` is intentionally excluded to avoid run data in export.
IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "archive",
    "exports",
    "runs",
    "gapsim.egg-info",
}

IGNORE_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "sources_dump.txt",
}

# Code-oriented text files to include.
INCLUDE_EXTS = {
    ".bat",
    ".cfg",
    ".cmd",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".pyi",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

INCLUDE_BASENAMES = {
    ".gitignore",
}

# Fast extension-level binary filter (plus null-byte fallback).
BINARY_EXTS = {
    ".7z",
    ".bmp",
    ".class",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".o",
    ".obj",
    ".pdf",
    ".png",
    ".pyc",
    ".pyd",
    ".pyo",
    ".so",
    ".svgz",
    ".tar",
    ".wav",
    ".webp",
    ".whl",
    ".zip",
}


def _is_ignored(rel_path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in rel_path.parts)


def _sorted(paths: List[Path]) -> List[Path]:
    return sorted(paths, key=lambda p: str(p.relative_to(ROOT)).replace("\\", "/").lower())


def _is_probably_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTS:
        return True
    try:
        raw = path.read_bytes()[:4096]
    except Exception:
        return True
    return b"\x00" in raw


def _read_text(path: Path) -> Tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=enc), enc
        except UnicodeDecodeError:
            continue

    return path.read_text(encoding="utf-8", errors="replace"), "utf-8(replace)"


def _collect_text_code_files() -> List[Path]:
    files: List[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        rel = path.relative_to(ROOT)
        if _is_ignored(rel):
            continue
        if path.name in IGNORE_FILE_NAMES:
            continue
        if path.suffix.lower() not in INCLUDE_EXTS and path.name not in INCLUDE_BASENAMES:
            continue
        if _is_probably_binary(path):
            continue

        files.append(path)

    return _sorted(files)


def _write_file_block(fp, path: Path, text: str, encoding: str) -> None:
    rel = path.relative_to(ROOT).as_posix()
    fp.write("\n" + "=" * 96 + "\n")
    fp.write(f"FILE: {rel}\n")
    fp.write(f"ENCODING: {encoding}\n")
    fp.write("=" * 96 + "\n")
    fp.write(text)
    if not text.endswith("\n"):
        fp.write("\n")


def main() -> int:
    now = datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    out_dir = EXPORT_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / "gfs_code_export.txt"
    text_files = _collect_text_code_files()

    skipped: List[Tuple[Path, str]] = []
    written_count = 0

    with out_file.open("w", encoding="utf-8", newline="\n") as fp:
        fp.write("GFS Code Export (runs excluded)\n")
        fp.write(f"Generated at: {now.isoformat(timespec='seconds')}\n")
        fp.write(f"Root: {ROOT}\n")
        fp.write(f"Excluded directories: {', '.join(sorted(IGNORE_DIRS))}\n")
        fp.write(f"Target text files: {len(text_files)}\n")

        fp.write("\n--- File List ---\n")
        for path in text_files:
            fp.write(f"- {path.relative_to(ROOT).as_posix()}\n")

        fp.write("\n--- File Contents ---\n")
        for path in text_files:
            try:
                text, enc = _read_text(path)
                _write_file_block(fp, path, text, enc)
                written_count += 1
            except Exception as exc:  # noqa: BLE001
                skipped.append((path, str(exc)))

        fp.write("\n--- Summary ---\n")
        fp.write(f"Written file blocks: {written_count}\n")
        fp.write(f"Skipped files: {len(skipped)}\n")
        if skipped:
            for path, reason in skipped:
                fp.write(f"- {path.relative_to(ROOT).as_posix()} :: {reason}\n")

    print(f"Dump complete: {out_file}")
    print(f"Output folder: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
