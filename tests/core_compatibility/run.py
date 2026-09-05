#!/usr/bin/env python3
"""Backward-compatible wrapper for the unified three-layer test runner."""

from __future__ import annotations

import sys

from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    runner = project_root / "tests" / "run.py"
    return __import__("subprocess").run(
        (sys.executable, str(runner), "system", "--all-cores", "--full"),
        cwd=project_root,
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
