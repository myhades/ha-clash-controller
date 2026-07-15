#!/usr/bin/env python3
"""Download and test all pinned Clash-compatible cores on this machine."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from download_core import MANIFEST_PATH, download_core


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "cores",
        nargs="*",
        help="Core names to test; defaults to every core in assets.json",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache/core-compatibility"),
    )
    args = parser.parse_args()

    with MANIFEST_PATH.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    cores = args.cores or list(manifest)
    unknown = sorted(set(cores) - set(manifest))
    if unknown:
        parser.error(f"unknown core(s): {', '.join(unknown)}")

    failures: list[str] = []
    for core in cores:
        binary = download_core(core, args.cache_dir)
        print(f"\n=== {core} {manifest[core]['version']} ===", flush=True)
        environment = {
            **os.environ,
            "CLASH_CORE_BINARY": str(binary),
            "CLASH_CORE_NAME": core,
        }
        result = subprocess.run(
            (
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:homeassistant",
                "-q",
                "-c",
                "tests/pytest.ini",
                "-m",
                "core_integration",
                "tests/core_compatibility/test_live_core.py",
            ),
            env=environment,
            check=False,
        )
        if result.returncode:
            failures.append(core)

    if failures:
        print(f"Failed cores: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
