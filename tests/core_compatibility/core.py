"""Real-core fixtures for Home Assistant system tests."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest
import pytest_socket
import yaml

SECRET = "ha-clash-controller-test-secret"


@dataclass
class RunningCore:
    """Controllable Clash-compatible core used by the system test suite."""

    name: str
    url: str
    proxy_url: str
    binary: Path
    work_dir: Path
    config_path: Path
    process: subprocess.Popen[str]

    def stop(self) -> None:
        """Stop the core without discarding its test configuration."""
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def start(self) -> None:
        """Start the core again on the same ports and configuration."""
        if self.process.poll() is None:
            return
        self.process = _start_process(self.binary, self.work_dir, self.config_path)
        _wait_until_ready(self.process, self.url)

    def restart(self) -> None:
        """Restart the core on the same controller URL."""
        self.stop()
        self.start()


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
            raise RuntimeError(
                f"Core exited with status {process.returncode} before startup"
            )
        try:
            with urlopen(request, timeout=1) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError):
            time.sleep(0.1)
    raise TimeoutError(f"Core did not expose {url}version within 20 seconds")


def _start_process(
    binary: Path, work_dir: Path, config_path: Path
) -> subprocess.Popen[str]:
    """Start one core process."""
    command = (
        (str(binary), "run", "-D", str(work_dir), "-c", str(config_path))
        if binary.name.startswith("sing_box-")
        else (str(binary), "-d", str(work_dir), "-f", str(config_path))
    )
    with (work_dir / "core.log").open("a") as log:
        return subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, text=True
        )


def create_running_core(binary: Path, core_name: str, work_dir: Path) -> RunningCore:
    """Create and start a core in a caller-owned temporary directory."""
    work_dir.mkdir(parents=True, exist_ok=True)
    database = os.environ.get("CLASH_TEST_DATABASE")
    if database:
        shutil.copyfile(database, work_dir / "Country.mmdb")
    controller_port = _free_port()
    proxy_port = _free_port()
    config_path = work_dir / "config.yaml"
    source_value = os.environ.get("CLASH_TEST_CONFIG")
    if source_value:
        source = Path(source_value).expanduser().resolve()
        loaded = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"Test config must contain a YAML mapping: {source}")
        config = loaded
    else:
        config = {
            "mode": "rule",
            "proxies": [],
            "proxy-groups": [],
            "rules": ["DOMAIN,example.com,DIRECT", "MATCH,DIRECT"],
        }

    groups = config.setdefault("proxy-groups", [])
    if not any(
        isinstance(group, dict) and group.get("name") == "HA Compatibility Test"
        for group in groups
    ):
        groups.append(
            {
                "name": "HA Compatibility Test",
                "type": "select",
                "proxies": ["DIRECT", "REJECT"],
            }
        )
    config.update(
        {
            "port": proxy_port,
            "allow-lan": False,
            "log-level": "silent",
            "external-controller": f"127.0.0.1:{controller_port}",
            "secret": SECRET,
        }
    )
    if core_name == "sing_box":
        if source_value:
            raise ValueError("--config accepts Clash YAML; omit it for sing-box")
        config = {
            "log": {"level": "error"},
            "experimental": {
                "clash_api": {
                    "external_controller": f"127.0.0.1:{controller_port}",
                    "secret": SECRET,
                    "default_mode": "rule",
                }
            },
            "inbounds": [
                {"type": "mixed", "listen": "127.0.0.1", "listen_port": proxy_port}
            ],
            "outbounds": [
                {"type": "direct", "tag": "DIRECT"},
                {"type": "direct", "tag": "SECOND"},
                {
                    "type": "selector",
                    "tag": "HA Compatibility Test",
                    "outbounds": ["DIRECT", "SECOND"],
                },
            ],
            "route": {
                "rules": [
                    {"clash_mode": "global", "action": "route", "outbound": "DIRECT"},
                    {"clash_mode": "rule", "action": "route", "outbound": "DIRECT"},
                ]
            },
        }
        config_path = work_dir / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
    else:
        config_path.write_text(
            yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    process = _start_process(binary, work_dir, config_path)
    url = f"http://127.0.0.1:{controller_port}/"
    core = RunningCore(
        core_name,
        url,
        f"http://127.0.0.1:{proxy_port}",
        binary,
        work_dir,
        config_path,
        process,
    )
    try:
        _wait_until_ready(process, url)
    except Exception as err:
        core.stop()
        log = (work_dir / "core.log").read_text(errors="replace")
        raise RuntimeError(f"{core_name} startup failed: {err}\n{log[-4000:]}") from err
    return core


@pytest.fixture(scope="session")
def running_core(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningCore]:
    """Start the core selected by the CI matrix or local environment."""
    pytest_socket.enable_socket()
    binary_value = os.environ.get("CLASH_CORE_BINARY")
    if not binary_value:
        pytest.skip("Set CLASH_CORE_BINARY to run real-core compatibility tests")

    binary = Path(binary_value).expanduser().resolve()
    if not binary.is_file():
        pytest.fail(f"CLASH_CORE_BINARY does not exist: {binary}")

    core_name = os.environ.get("CLASH_CORE_NAME", binary.name)
    work_dir = tmp_path_factory.mktemp(f"core-{core_name}")
    core = create_running_core(binary, core_name, work_dir)
    try:
        yield core
    finally:
        core.stop()
