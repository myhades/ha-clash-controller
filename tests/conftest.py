"""Shared pytest config for clash_controller."""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REAL_CORE_TEST = bool(os.environ.get("CLASH_CORE_BINARY"))

if sys.platform != "win32" and not REAL_CORE_TEST:
    pytest_plugins = ("pytest_homeassistant_custom_component",)


if sys.platform != "win32" and not REAL_CORE_TEST:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Enable loading custom integrations in test harness."""
        yield
