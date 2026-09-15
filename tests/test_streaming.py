"""Streaming detector contracts using local responses."""

import aiohttp
import pytest
from aiohttp import web

from custom_components.clash_controller.streaming import StreamingDetector

pytestmark = pytest.mark.enable_socket


@pytest.mark.parametrize("status", [200, 403, 404])
async def test_streaming_status(aiohttp_server, status):
    async def handler(request):
        return web.Response(status=status)

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    async with aiohttp.ClientSession() as session:
        result = await StreamingDetector(session).async_get_url_status(
            str(server.make_url("/"))
        )
        assert result["status_code"] == status
        assert result["latency"] >= 0
