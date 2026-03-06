"""Shared pytest config for clash_controller."""

import sys

import pytest

if sys.platform != "win32":
    pytest_plugins = ("pytest_homeassistant_custom_component",)


if sys.platform != "win32":

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Enable loading custom integrations in test harness."""
        yield
