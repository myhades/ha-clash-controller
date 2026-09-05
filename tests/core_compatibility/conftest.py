"""Fixtures shared by real-core system tests."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
import subprocess
import sys

import pytest
import pytest_asyncio

from .fault_proxy import ControllerFaultProxy
from .test_live_core import RunningCore
from .test_live_core import running_core


@pytest.fixture
def hanging_api_url() -> Iterator[str]:
    """Expose a controller URL which accepts requests but never responds."""
    script = Path(__file__).with_name("hanging_server.py")
    process = subprocess.Popen(
        (sys.executable, str(script)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert process.stdout is not None
    port = int(process.stdout.readline().strip())
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest_asyncio.fixture
async def fault_proxy(
    running_core: RunningCore, aiohttp_server
) -> AsyncIterator[ControllerFaultProxy]:
    """Forward requests to the real core with controllable endpoint faults."""
    proxy = ControllerFaultProxy(running_core.url)
    server = await aiohttp_server(proxy.app())
    proxy.url = str(server.make_url("/"))
    try:
        yield proxy
    finally:
        await proxy.close()


__all__ = ["fault_proxy", "hanging_api_url", "running_core"]
