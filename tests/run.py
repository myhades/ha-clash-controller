#!/usr/bin/env python3
"""Run Home Assistant integration, system, and release validation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from core_compatibility.download_core import (
    MANIFEST_PATH,
    download_core,
    download_test_database,
)


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
    database = download_test_database(cache_dir)
    expression = (
        "system" if include_release and core == "mihomo" else "system and not release"
    )
    environment = {
        **os.environ,
        "CLASH_CORE_BINARY": str(binary),
        "CLASH_CORE_NAME": core,
        "CLASH_TEST_DATABASE": str(database),
    }
    if config_path is not None:
        environment["CLASH_TEST_CONFIG"] = str(config_path.resolve())
    print(f"\n=== system: {core} ===", flush=True)
    return _pytest("-m", expression, environment=environment)


def main() -> int:
    """Run integration, system, or release validation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "layer",
        choices=("integration", "system", "release"),
        help="integration runs HA contracts; system runs real cores; release runs both plus process recovery",
    )
    parser.add_argument(
        "--core",
        action="append",
        dest="cores",
        help="restrict system validation to selected cores; may be repeated (default: all)",
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

    if args.layer == "integration":
        return _pytest("-m", "not system")

    with MANIFEST_PATH.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if args.cores:
        unknown = sorted(set(args.cores) - set(manifest))
        if unknown:
            parser.error(f"unknown core(s): {', '.join(unknown)}")
    cores = (
        list(manifest)
        if args.all_cores or args.layer == "release"
        else (args.cores or list(manifest))
    )
    include_release = args.full or args.layer == "release"

    failures: list[str] = []
    if args.layer == "release" and _pytest("-m", "not system"):
        failures.append("integration")
    for core in cores:
        try:
            result = _run_core(
                core,
                include_release=include_release,
                cache_dir=args.cache_dir,
                config_path=args.config,
            )
        except (OSError, RuntimeError, ValueError) as err:
            print(f"{core}: {err}", file=sys.stderr)
            result = 1
        if result:
            failures.append(core)

    if failures:
        print(f"Failed test targets: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
