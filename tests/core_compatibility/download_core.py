#!/usr/bin/env python3
"""Download and verify a pinned Clash-compatible test core."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
from typing import Any
from urllib.request import Request, urlopen

MANIFEST_PATH = Path(__file__).with_name("assets.json")


def _platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    machine = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine, machine)
    return f"{system}-{machine}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest() -> dict[str, dict[str, Any]]:
    with MANIFEST_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def download_core(core: str, output_dir: Path) -> Path:
    """Return an executable path, downloading it when it is not cached."""
    manifest = _load_manifest()
    if core not in manifest:
        choices = ", ".join(sorted(manifest))
        raise ValueError(f"Unknown core {core!r}; choose one of: {choices}")

    platform_key = _platform_key()
    core_data = manifest[core]
    asset = core_data["platforms"].get(platform_key)
    if asset is None:
        supported = ", ".join(sorted(core_data["platforms"]))
        raise RuntimeError(
            f"{core} has no {platform_key} test asset; supported: {supported}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    version = str(core_data["version"]).replace("/", "-")
    archive = output_dir / f"{core}-{version}-{platform_key}.gz"
    executable = output_dir / f"{core}-{version}-{platform_key}"
    expected_hash = asset["sha256"]

    if archive.exists() and _sha256(archive) != expected_hash:
        archive.unlink()
        executable.unlink(missing_ok=True)

    if not archive.exists():
        request = Request(asset["url"], headers={"User-Agent": "ha-clash-controller-tests"})
        with tempfile.NamedTemporaryFile(dir=output_dir, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                with urlopen(request, timeout=60) as response:
                    shutil.copyfileobj(response, temporary)
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise
        actual_hash = _sha256(temporary_path)
        if actual_hash != expected_hash:
            temporary_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA-256 mismatch for {core}: expected {expected_hash}, got {actual_hash}"
            )
        temporary_path.replace(archive)

    if not executable.exists():
        with gzip.open(archive, "rb") as compressed, tempfile.NamedTemporaryFile(
            dir=output_dir, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            try:
                shutil.copyfileobj(compressed, temporary)
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise
        temporary_path.replace(executable)

    executable.chmod(executable.stat().st_mode | 0o111)
    return executable.resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("core", nargs="?", help="Core name from assets.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".cache/core-compatibility"),
        help="Cache directory for archives and executables",
    )
    parser.add_argument("--list", action="store_true", help="List pinned cores")
    args = parser.parse_args()

    manifest = _load_manifest()
    if args.list:
        for name, data in manifest.items():
            print(f"{name}\t{data['version']}\t{data['source']}")
        return 0
    if not args.core:
        parser.error("core is required unless --list is used")

    try:
        print(download_core(args.core, args.output_dir))
    except (OSError, RuntimeError, ValueError) as err:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
