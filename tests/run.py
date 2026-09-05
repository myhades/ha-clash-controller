#!/usr/bin/env python3
"""Run the three-layer Clash Controller test system."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from core_compatibility.download_core import MANIFEST_PATH, download_core


def _pytest(*args: str, environment: dict[str, str] | None = None) -> int:
    """Run pytest with the repository's shared configuration."""
    return subprocess.run(
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-c",
            "tests/pytest.ini",
            *args,
            "tests",
        ),
        env=environment,
        check=False,
    ).returncode


def _run_core(
    core: str,
    *,
    include_release: bool,
    cache_dir: Path,
    config_path: Path | None,
) -> int:
    """Run the system suite against one pinned core."""
    binary = download_core(core, cache_dir)
    expression = "system" if include_release else "system and not release"
    environment = {
        **os.environ,
        "CLASH_CORE_BINARY": str(binary),
        "CLASH_CORE_NAME": core,
    }
    if config_path is not None:
        environment["CLASH_TEST_CONFIG"] = str(config_path.resolve())
    print(f"\n=== system: {core} ===", flush=True)
    return _pytest("-m", expression, environment=environment)


def main() -> int:
    """Run unit, system, or release validation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "layer",
        choices=("unit", "system", "release"),
        help="unit is fast; system uses real HA/core; release runs the full matrix",
    )
    parser.add_argument(
        "--core",
        action="append",
        dest="cores",
        help="core to test in the system layer; may be repeated (default: mihomo)",
    )
    parser.add_argument(
        "--all-cores",
        action="store_true",
        help="run every core pinned in assets.json",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="include slower outage and lifecycle scenarios in the system layer",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache/core-compatibility"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="optional Clash YAML used as the base for generated test configs",
    )
    args = parser.parse_args()

    if args.layer == "unit":
        return _pytest("-m", "not system")

    with MANIFEST_PATH.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if args.cores:
        unknown = sorted(set(args.cores) - set(manifest))
        if unknown:
            parser.error(f"unknown core(s): {', '.join(unknown)}")
    cores = list(manifest) if args.all_cores or args.layer == "release" else (args.cores or ["mihomo"])
    include_release = args.full or args.layer == "release"

    failures: list[str] = []
    if args.layer == "release" and _pytest("-m", "not system"):
        failures.append("unit")
    for core in cores:
        if _run_core(
            core,
            include_release=include_release,
            cache_dir=args.cache_dir,
            config_path=args.config,
        ):
            failures.append(core)

    if failures:
        print(f"Failed test targets: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
