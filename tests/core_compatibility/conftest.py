"""Fixtures for real-core compatibility and release smoke tests."""

import pytest

from .core import running_core as running_core


@pytest.fixture(autouse=True)
def enable_real_core_sockets(socket_enabled):
    """Allow localhost core requests after HA installs its socket guard."""
    yield
