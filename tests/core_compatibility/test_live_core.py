"""Compatibility contract tests against a real Clash-compatible core."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

API_PATH = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "clash_controller"
    / "api.py"
)
API_SPEC = importlib.util.spec_from_file_location("clash_controller_live_api", API_PATH)
assert API_SPEC and API_SPEC.loader
API_MODULE = importlib.util.module_from_spec(API_SPEC)
API_SPEC.loader.exec_module(API_MODULE)
APIAuthError = API_MODULE.APIAuthError
ClashAPI = API_MODULE.ClashAPI

pytestmark = pytest.mark.core_integration

SECRET = "ha-clash-controller-test-secret"


@dataclass(frozen=True)
class RunningCore:
    """Details for a core process started by the test suite."""

    name: str
    url: str
    process: subprocess.Popen[str]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(process: subprocess.Popen[str], url: str) -> None:
    request = Request(
        f"{url}version",
        headers={"Authorization": f"Bearer {SECRET}"},
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, _ = process.communicate()
            raise RuntimeError(
                f"Core exited with status {process.returncode} before startup:\n{stdout}"
            )
        try:
            with urlopen(request, timeout=1) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError):
            time.sleep(0.1)
    raise TimeoutError(f"Core did not expose {url}version within 20 seconds")


@pytest.fixture(scope="module")
def running_core(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningCore]:
    """Start the core selected by the CI matrix or local environment."""
    binary_value = os.environ.get("CLASH_CORE_BINARY")
    if not binary_value:
        pytest.skip("Set CLASH_CORE_BINARY to run real-core compatibility tests")

    binary = Path(binary_value).expanduser().resolve()
    if not binary.is_file():
        pytest.fail(f"CLASH_CORE_BINARY does not exist: {binary}")

    core_name = os.environ.get("CLASH_CORE_NAME", binary.name)
    controller_port = _free_port()
    proxy_port = _free_port()
    work_dir = tmp_path_factory.mktemp(f"core-{core_name}")
    config_path = work_dir / "config.yaml"
    config_path.write_text(
        "\n".join(
            (
                f"port: {proxy_port}",
                "allow-lan: false",
                "mode: rule",
                "log-level: silent",
                f"external-controller: 127.0.0.1:{controller_port}",
                f"secret: {SECRET}",
                "proxies: []",
                "proxy-groups:",
                "  - name: HA Compatibility Test",
                "    type: select",
                "    proxies:",
                "      - DIRECT",
                "      - REJECT",
                "rules:",
                "  - DOMAIN,example.com,DIRECT",
                "  - MATCH,DIRECT",
                "",
            )
        ),
        encoding="utf-8",
    )

    process = subprocess.Popen(
        (str(binary), "-d", str(work_dir), "-f", str(config_path)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{controller_port}/"
    try:
        _wait_until_ready(process, url)
        yield RunningCore(core_name, url, process)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.asyncio
async def test_detects_and_reads_supported_endpoints(running_core: RunningCore) -> None:
    """Detected endpoints must return payloads the integration can consume."""
    api = ClashAPI(running_core.url, SECRET)
    try:
        assert await api.connected(suppress_errors=False)
        version = await api.get_version()
        assert version["version"] != "unknown"

        capabilities = await api.async_detect_capabilities(force=True)
        for required in ("proxies", "connections", "traffic", "configs", "rules"):
            assert capabilities[required], (
                f"{running_core.name} did not expose required capability {required}"
            )

        data = await api.fetch_data(suppress_errors=False)
        assert isinstance(data["proxies"].get("proxies"), dict)
        # Empty connection sets are encoded as null by Meta cores and [] by
        # some Clash builds. The coordinator intentionally accepts both.
        assert data["connections"].get("connections") is None or isinstance(
            data["connections"]["connections"], list
        )
        assert {"uploadTotal", "downloadTotal"} <= data["connections"].keys()
        assert {"up", "down"} <= data["traffic"].keys()
        assert isinstance(data["configs"], dict)

        if capabilities["memory"]:
            assert "inuse" in data["memory"]
        if capabilities["providers_proxies"]:
            assert isinstance(data["providers_proxies"].get("providers"), dict)
        if capabilities["providers_rules"]:
            assert isinstance(data["providers_rules"].get("providers"), dict)

        rules = await api.async_request("GET", "rules", suppress_errors=False)
        assert isinstance(rules.get("rules"), list)
        assert rules["rules"]
        assert {"type", "payload", "proxy"} <= rules["rules"][0].keys()

        if capabilities["group"]:
            groups = await api.async_request("GET", "group", suppress_errors=False)
            assert isinstance(groups.get("proxies"), list)

        if capabilities["ws_traffic"]:
            assert {"up", "down"} <= (
                await api.async_ws_request("traffic", suppress_errors=False)
            ).keys()
        if capabilities["ws_connections"]:
            assert "connections" in await api.async_ws_request(
                "connections?interval=1", suppress_errors=False
            )

    finally:
        await api.close_session()


@pytest.mark.asyncio
async def test_rejects_invalid_token(running_core: RunningCore) -> None:
    """The real core's 401 response must map to APIAuthError."""
    api = ClashAPI(running_core.url, "wrong-secret")
    try:
        with pytest.raises(APIAuthError):
            await api.connected(suppress_errors=False)
    finally:
        await api.close_session()


@pytest.mark.asyncio
async def test_reads_and_switches_selector(running_core: RunningCore) -> None:
    """Exercise the selector read/write path shared by all claimed cores."""
    api = ClashAPI(running_core.url, SECRET)
    group_name = "HA Compatibility Test"
    endpoint = f"proxies/{quote(group_name, safe='')}"
    try:
        group = await api.async_request("GET", endpoint, suppress_errors=False)
        assert group["now"] == "DIRECT"
        assert {"DIRECT", "REJECT"} <= set(group["all"])

        await api.async_request(
            "PUT",
            endpoint,
            json_data={"name": "REJECT"},
            suppress_errors=False,
        )
        updated = await api.async_request("GET", endpoint, suppress_errors=False)
        assert updated["now"] == "REJECT"
    finally:
        await api.async_request(
            "PUT",
            endpoint,
            json_data={"name": "DIRECT"},
            suppress_errors=True,
        )
        await api.close_session()
