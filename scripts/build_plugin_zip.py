#!/usr/bin/env python3
"""Build the installable plugin ZIP for claude.ai upload.

Zips ``plugin/nba-three-leg-parlays`` so that the plugin folder is the single top-level
entry of the archive (``nba-three-leg-parlays/.claude-plugin/plugin.json`` and so on),
which is one of the two layouts claude.ai's Upload plugin accepts. Output goes to
``dist/nba-three-leg-parlays-<version>.zip`` where ``<version>`` is read from the
manifest.

Plain Python 3.12, standard library only. Usage::

    python3 scripts/build_plugin_zip.py            # build the archive
    python3 scripts/build_plugin_zip.py --dry-run  # list what would be zipped, write nothing

Exit codes: 0 success, 1 a blocking problem was found in the plugin folder, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLUGIN_DIR = PROJECT_ROOT / "plugin" / "nba-three-leg-parlays"
DEFAULT_DIST_DIR = PROJECT_ROOT / "dist"

# Names the directory validator blocks or that never belong in a bundle.
EXCLUDED_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", "__MACOSX", "__pycache__", ".git"})
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".zip")
# Directory file rules (pre-submission checklist, retrieved 2026-10-19): non-image/font files under 256 KiB.
MAX_TEXT_FILE_BYTES = 256 * 1024
IMAGE_OR_FONT_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ttf", ".otf", ".woff", ".woff2")
MAX_FILES = 512


@dataclass(frozen=True)
class Entry:
    """One file selected for the archive."""

    path: Path
    arcname: str
    size: int


def read_manifest(plugin_dir: Path) -> dict[str, object]:
    """Return the parsed ``.claude-plugin/plugin.json`` or raise ``FileNotFoundError``/``ValueError``."""
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        raise ValueError("plugin.json must be an object with a string 'name'")
    return data


def is_excluded(path: Path) -> bool:
    """True when the file or any of its parent folders must stay out of the archive."""
    if any(part in EXCLUDED_NAMES for part in path.parts):
        return True
    return path.name.endswith(EXCLUDED_SUFFIXES)


def collect_entries(plugin_dir: Path) -> list[Entry]:
    """Walk the plugin folder and return the files to archive, sorted by archive name."""
    top = plugin_dir.name
    entries: list[Entry] = []
    for root, dirs, files in os.walk(plugin_dir):
        root_path = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_NAMES)
        for name in sorted(files):
            file_path = root_path / name
            rel = file_path.relative_to(plugin_dir)
            if is_excluded(rel) or file_path.is_symlink():
                continue
            entries.append(
                Entry(path=file_path, arcname=f"{top}/{rel.as_posix()}", size=file_path.stat().st_size)
            )
    return entries


def check_blocking(plugin_dir: Path, entries: list[Entry]) -> list[str]:
    """Return blocking problems that would make the bundle unusable or un-submittable."""
    problems: list[str] = []
    if not (plugin_dir / ".claude-plugin" / "plugin.json").is_file():
        problems.append(".claude-plugin/plugin.json is missing")
    extra_in_manifest_dir = [
        p.name for p in (plugin_dir / ".claude-plugin").glob("*") if p.name != "plugin.json"
    ]
    if extra_in_manifest_dir:
        problems.append(
            f"only plugin.json belongs inside .claude-plugin/, found: {', '.join(extra_in_manifest_dir)}"
        )
    if (plugin_dir / "bin").exists():
        problems.append("top-level bin/ blocks installation on claude.ai and Cowork")
    if (plugin_dir / "CLAUDE.md").exists():
        problems.append(
            "CLAUDE.md at the plugin root is not loaded and triggers a validate warning; remove it"
        )
    for lock in ("uv.lock", "package-lock.json", "poetry.lock", "yarn.lock", "pnpm-lock.yaml"):
        if (plugin_dir / lock).exists():
            problems.append(f"lockfile {lock} inside the plugin folder is held for review; remove it")
    if not (plugin_dir / "README.md").is_file():
        problems.append("README.md is missing (directory requires at least 40 words)")
    if not (plugin_dir / "LICENSE").is_file():
        problems.append("LICENSE is missing")
    if len(entries) > MAX_FILES:
        problems.append(f"{len(entries)} files exceeds the directory limit of {MAX_FILES}")
    for entry in entries:
        suffix = entry.path.suffix.lower()
        if suffix not in IMAGE_OR_FONT_SUFFIXES and entry.size > MAX_TEXT_FILE_BYTES:
            problems.append(
                f"{entry.arcname} is {entry.size} bytes, over the 256 KiB limit for non-image files"
            )
    return problems


def format_size(num: int) -> str:
    """Human-readable byte count."""
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.1f} KiB"
    return f"{num / (1024 * 1024):.2f} MiB"


def build(plugin_dir: Path, dist_dir: Path, *, dry_run: bool) -> Path:
    """Validate the folder, print the file list, and write the archive unless ``dry_run``."""
    manifest = read_manifest(plugin_dir)
    name = str(manifest["name"])
    version = str(manifest.get("version") or "unversioned")
    entries = collect_entries(plugin_dir)
    problems = check_blocking(plugin_dir, entries)

    print(f"plugin: {name} version {version}")
    print(f"source: {plugin_dir}")
    total = 0
    for entry in entries:
        total += entry.size
        print(f"  {entry.arcname}  ({format_size(entry.size)})")
    print(f"{len(entries)} files, {format_size(total)} uncompressed")

    if problems:
        print("blocking problems:")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)

    zip_path = dist_dir / f"{name}-{version}.zip"
    if dry_run:
        print(f"dry run: would write {zip_path}")
        return zip_path

    dist_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            archive.write(entry.path, entry.arcname)
    print(f"wrote {zip_path} ({format_size(zip_path.stat().st_size)} compressed)")
    return zip_path


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--plugin-dir", type=Path, default=DEFAULT_PLUGIN_DIR, help="plugin folder to zip")
    parser.add_argument("--dist-dir", type=Path, default=DEFAULT_DIST_DIR, help="output folder")
    parser.add_argument(
        "--dry-run", action="store_true", help="list files and the target path, write nothing"
    )
    args = parser.parse_args(argv)
    try:
        build(args.plugin_dir.resolve(), args.dist_dir.resolve(), dry_run=args.dry_run)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
