import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "acceptance_probe", Path(__file__).resolve().parents[2] / "scripts/acceptance_probe.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
URL = "http://127.0.0.1:8000/api/v1/health"
PRIVATE = "synthetic-private-never-write"


def health():
    return {
        "status": "ok",
        "uptime": 42,
        "db_connected": True,
        "ha_connected": True,
        "db_size_bytes": 123,
        "services": {
            "database": "ready",
            "llm": "ready",
            "unknown_service": PRIVATE,
            "voice": PRIVATE,
        },
        "raw": PRIVATE,
        "ha_status": PRIVATE,
    }


@pytest.fixture
def resources(monkeypatch):
    monkeypatch.setattr(probe.shutil, "disk_usage", lambda _: SimpleNamespace(free=8 * 1024**3))
    monkeypatch.setattr(
        probe,
        "host_metrics",
        lambda: dict(
            MemTotal=8 * 1024**3,
            MemAvailable=1024**3,
            SwapTotal=0,
            SwapFree=0,
            boot="synthetic-boot",
            uptime_seconds=42,
        ),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/api/v1/health",
        "http://8.8.8.8/api/v1/health",
        "http://192.0.2.1/api/v1/health",
        "http://localhost/api/v1/health",
        "http://127.0.0.1:0/api/v1/health",
        "http://127.0.0.1:99999/api/v1/health",
        "http://user:password@127.0.0.1/api/v1/health",
        "http://127.0.0.1/api/v1/health?x=1",
        "http://127.0.0.1/api/v1/health#x",
        "http://127.0.0.1/api/v1/devices",
        "file:///api/v1/health",
        "http://[::ffff:8.8.8.8]/api/v1/health",
    ],
)
def test_refuses_nonlocal_or_credential_url(url):
    with pytest.raises(probe.ProbeError, match="LOCAL_HEALTH_URL_REQUIRED"):
        probe.local_endpoint(url)


def test_health_transport_no_dns_proxy_auth_or_redirect(monkeypatch):
    requests = []
    connections = []
    body = json.dumps(health()).encode()
    packet = b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body

    class Socket:
        closed = False

        def __init__(self, *_):
            self.blocks = [packet, b""]
            connections.append(self)

        def settimeout(self, value):
            assert 0 < value <= 8

        def connect(self, address):
            assert address == ("127.0.0.1", 8000)

        def sendall(self, data):
            requests.append(data)

        def recv(self, _):
            return self.blocks.pop(0)

        def close(self):
            self.closed = True

    monkeypatch.setattr(probe.socket, "socket", Socket)
    monkeypatch.setenv("HTTP_PROXY", "http://invalid-proxy:1234")
    result = probe.fetch_health(probe.local_endpoint(URL))
    assert result["health"]["services"]["voice"] == "unknown"
    assert PRIVATE not in json.dumps(result)
    assert b"GET /api/v1/health HTTP/1.1" in requests[0]
    assert b"Authorization" not in requests[0] and connections[0].closed
    packet = b"HTTP/1.1 302 Found\r\nLocation: https://example.com/\r\nContent-Length: 0\r\n\r\n"
    assert probe.fetch_health(probe.local_endpoint(URL)) == {"error": "REDIRECT_REFUSED"}
    assert len(connections) == 2
    packet = b"HTTP/1.1 200 OK\r\n\r\n" + b"x" * 74000
    assert probe.fetch_health(probe.local_endpoint(URL)) == {"error": "RESPONSE_TOO_LARGE"}
    packet = b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n{}"
    assert probe.fetch_health(probe.local_endpoint(URL)) == {"error": "INVALID_HTTP"}


def test_closed_output_bounded_samples_and_sanitization(tmp_path, resources, monkeypatch):
    monkeypatch.setattr(
        probe, "fetch_health", lambda _: {"health": probe.sanitize_health(health())}
    )
    target = tmp_path / "private/probe.jsonl"
    result = probe.run(URL, target)
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    assert result["samples"] == 1 and result["health_ok"] == 1
    assert result["hardware_acceptance"] is False and rows[-1]["type"] == "summary"
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert PRIVATE not in target.read_text() and "127.0.0.1" not in target.read_text()
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        probe.run(URL, target)
    assert target.read_bytes() == before
    with pytest.raises(probe.ProbeError, match="INVALID_SAMPLE_BUDGET"):
        probe.run(URL, tmp_path / "invalid", samples=probe.MAX_SAMPLES + 1)


def test_low_resources_dont_create_or_overwrite(tmp_path, resources, monkeypatch):
    monkeypatch.setattr(probe.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    output = tmp_path / "probe.jsonl"
    with pytest.raises(probe.ProbeError, match="DISK_RESERVE"):
        probe.run(URL, output)
    assert not output.exists()
    monkeypatch.setattr(probe.shutil, "disk_usage", lambda _: SimpleNamespace(free=8 * 1024**3))
    monkeypatch.setattr(probe, "host_metrics", lambda: {"MemAvailable": 1})
    result = probe.run(URL, output)
    assert result["samples"] == 0 and result["stopped_for"] == "SHARED_RAM_RESERVE"
    assert json.loads(output.read_text().splitlines()[-1])["type"] == "summary"


def test_process_instances_children_and_cgroup(tmp_path):
    def process(pid, parent, start, rss, children=""):
        directory = tmp_path / str(pid)
        directory.mkdir()
        fields = ["0"] * 22
        fields[0], fields[1], fields[19], fields[21] = "S", str(parent), str(start), str(rss)
        (directory / "stat").write_text(f"{pid} (name with ) parentheses) " + " ".join(fields))
        task = directory / "task" / str(pid)
        task.mkdir(parents=True)
        (task / "children").write_text(children)

    process(1, 0, 100, 10, "2 3")
    process(2, 1, 101, 20)
    process(3, 99, 102, 500)
    data = probe.family_metrics(1, 100, tmp_path)
    assert data["rss_sum_bytes"] == 30 * os.sysconf("SC_PAGE_SIZE") and data["processes"] == 2
    with pytest.raises(probe.ProbeError, match="MONITORED_PROCESS_CHANGED"):
        probe.family_metrics(1, 200, tmp_path)
    (tmp_path / "memory.current").write_text("1234\n")
    (tmp_path / "memory.events").write_text("oom 0\noom_kill 2\n")
    data = probe.cgroup_metrics(tmp_path)
    assert data["memory.current"] == 1234 and data["oom_kill"] == 2
    assert data["memory.peak"] is None


def test_observed_discontinuities():
    before = dict(elapsed=0, unix=100, host={"boot": "a"}, probe={"health": {"uptime": 200}})
    after = dict(elapsed=200, unix=700, host={"boot": "b"}, probe={"health": {"uptime": 3}})
    assert set(probe.discontinuities(before, after, 60)) == {
        "host_boot_changed",
        "sampling_gap",
        "wall_clock_jump",
        "core_restart",
    }


def test_refuse_output_symlinks_public_directory_and_invalid_pid(tmp_path, resources):
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(probe.ProbeError, match="OUTPUT_DIRECTORY_MUST_BE_PRIVATE"):
        probe.run(URL, public / "probe")
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(probe.ProbeError, match="UNSAFE_OUTPUT"):
        probe.run(URL, link / "probe")
    with pytest.raises(probe.ProbeError, match="INVALID_PID"):
        probe.run(URL, tmp_path / "probe", pid=0)
