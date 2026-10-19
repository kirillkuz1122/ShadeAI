"""Ограниченный read-only сбор метрик приёмки. Не выдаёт аппаратный PASS."""

import argparse
import hashlib
import http.client
import io
import ipaddress
import json
import os
import platform
import shutil
import socket
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

RESERVE = 4 * 1024**3
MAX_BYTES = 32 * 1024**2
MAX_SAMPLES = 20161
LOCAL = tuple(
    ipaddress.ip_network(value)
    for value in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
    )
)
SERVICES = (
    "database",
    "home_assistant",
    "llm",
    "notification_worker",
    "analytics",
    "voice",
    "temporary_access",
    "meeting_mode",
    "calendar",
    "suggestions",
    "automation_executor",
)
STATES = {
    "ok",
    "degraded",
    "error",
    "ready",
    "unavailable",
    "connected",
    "disabled",
    "starting",
    "not_loaded",
    "loading",
    "idle",
    "processing",
    "stopped",
    "storage_error",
    "waiting_model",
    "model_unavailable",
    "calculating",
    "insufficient_data",
    "not_configured",
    "configured",
    "busy",
    "closed",
    "syncing",
    "restoring",
    "capacity",
    "unknown",
}


class ProbeError(Exception):
    pass


def local_endpoint(url: str):
    try:
        parsed = urlsplit(url)
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or "?" in url
            or "#" in url
            or "%" in url
            or parsed.path != "/api/v1/health"
            or not 1 <= port <= 65535
            or not any(address in network for network in LOCAL)
        ):
            raise ValueError
        return parsed.scheme, address, port
    except ValueError as exc:
        raise ProbeError("LOCAL_HEALTH_URL_REQUIRED") from exc


def bounded_int(value, maximum=2**63 - 1):
    return value if type(value) is int and 0 <= value <= maximum else None


def sanitize_health(data):
    if not isinstance(data, dict):
        raise ProbeError("INVALID_HEALTH")
    services = data.get("services")
    if not isinstance(services, dict):
        raise ProbeError("INVALID_HEALTH")

    def state(value):
        return value if isinstance(value, str) and value in STATES else "unknown"

    return {
        "status": state(data.get("status")),
        "uptime": bounded_int(data.get("uptime")),
        "db_connected": data.get("db_connected")
        if type(data.get("db_connected")) is bool
        else None,
        "ha_connected": data.get("ha_connected")
        if type(data.get("ha_connected")) is bool
        else None,
        "db_size_bytes": bounded_int(data.get("db_size_bytes")),
        "services": {name: state(services.get(name)) for name in SERVICES},
    }


def fetch_health(endpoint, timeout=8):
    scheme, address, port = endpoint
    started = time.monotonic()
    deadline = started + timeout
    connection = socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET)

    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError
        connection.settimeout(value)

    try:
        # Числовой IP передаётся socket.connect напрямую: getaddrinfo/DNS/proxy не нужны.
        remaining()
        connection.connect((str(address), port))
        if scheme == "https":
            remaining()
            connection = ssl.create_default_context().wrap_socket(
                connection, server_hostname=str(address)
            )
        host = f"[{address}]" if address.version == 6 else str(address)
        remaining()
        connection.sendall(
            (
                f"GET /api/v1/health HTTP/1.1\r\nHost: {host}:{port}\r\n"
                "Accept: application/json\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
        )
        raw = bytearray()
        while True:
            remaining()
            block = connection.recv(8192)
            if not block:
                break
            raw.extend(block)
            if len(raw) > 73728:
                raise ProbeError("RESPONSE_TOO_LARGE")
        header_end = raw.find(b"\r\n\r\n")
        if header_end < 0 or header_end > 8192:
            raise ProbeError("INVALID_HTTP")

        class BufferedSocket:
            def makefile(self, *_):
                return io.BytesIO(raw)

        response = http.client.HTTPResponse(BufferedSocket())
        response.begin()
        if 300 <= response.status < 400:
            raise ProbeError("REDIRECT_REFUSED")
        if response.status not in {200, 503}:
            raise ProbeError("HTTP_STATUS")
        body = response.read(65537)
        if len(body) > 65536:
            raise ProbeError("RESPONSE_TOO_LARGE")
        if response.length not in {None, 0}:
            raise ProbeError("INVALID_HTTP")
        health = sanitize_health(json.loads(body))
        return {
            "http_status": response.status,
            "health": health,
            "health_latency_ms": round((time.monotonic() - started) * 1000, 2),
        }
    except ProbeError as exc:
        return {"error": str(exc)}
    except TimeoutError:
        return {"error": "TIMEOUT"}
    except (ValueError, OSError, http.client.HTTPException, RecursionError):
        return {"error": "UNREACHABLE_OR_INVALID_RESPONSE"}
    finally:
        connection.close()


def read_limited(path, limit=4096):
    with Path(path).open("rb") as file:
        return file.read(limit).decode("ascii", errors="strict")


def host_metrics(proc=Path("/proc")):
    fields = {}
    for line in read_limited(proc / "meminfo").splitlines():
        name, _, value = line.partition(":")
        if name in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            fields[name] = int(value.split()[0]) * 1024
    if len(fields) != 4:
        raise ProbeError("HOST_METRICS_UNAVAILABLE")
    boot = read_limited(proc / "sys/kernel/random/boot_id", 64).strip()
    fields["boot"] = hashlib.sha256(boot.encode()).hexdigest()[:16]
    fields["uptime_seconds"] = float(read_limited(proc / "uptime", 128).split()[0])
    return fields


def process_info(pid, proc=Path("/proc")):
    try:
        directory = proc / str(pid)
        if directory.stat().st_uid != os.getuid():
            return None
        fields = read_limited(directory / "stat").rsplit(")", 1)[1].split()
        return {
            "start": int(fields[19]),
            "rss": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
            "parent": int(fields[1]),
        }
    except (OSError, ValueError, IndexError):
        return None


def family_metrics(pid, expected, proc=Path("/proc")):
    root = process_info(pid, proc)
    if root is None or root["start"] != expected:
        raise ProbeError("MONITORED_PROCESS_CHANGED")
    queue = [(pid, root)]
    seen = {pid}
    rss = 0
    truncated = False
    while queue:
        current, info = queue.pop()
        rss += info["rss"]
        tasks = proc / str(current) / "task"
        try:
            for number, thread in enumerate(tasks.iterdir()):
                if number >= 256:
                    truncated = True
                    break
                for child in read_limited(thread / "children", 2048).split():
                    child = int(child)
                    data = process_info(child, proc)
                    if child in seen or data is None or data["parent"] != current:
                        continue
                    if len(seen) >= 128:
                        truncated = True
                        continue
                    seen.add(child)
                    queue.append((child, data))
        except (OSError, ValueError):
            truncated = True
    return {"rss_sum_bytes": rss, "processes": len(seen), "truncated": truncated}


def cgroup_metrics(directory):
    if directory is None:
        return None
    result = {}
    for name in ("memory.current", "memory.peak", "memory.swap.current"):
        try:
            result[name] = bounded_int(int(read_limited(directory / name, 64).strip()))
        except (OSError, ValueError):
            result[name] = None
    try:
        result["oom_kill"] = next(
            int(line.split()[1])
            for line in read_limited(directory / "memory.events", 1024).splitlines()
            if line.startswith("oom_kill ")
        )
    except (OSError, ValueError, StopIteration):
        result["oom_kill"] = None
    return result


def discontinuities(previous, current, interval):
    if previous is None:
        return []
    flags = []
    elapsed = current["elapsed"] - previous["elapsed"]
    if current["host"]["boot"] != previous["host"]["boot"]:
        flags.append("host_boot_changed")
    if elapsed < 0:
        flags.append("monotonic_backwards")
    if elapsed > max(interval * 2, interval + 10):
        flags.append("sampling_gap")
    wall = current["unix"] - previous["unix"]
    if abs(wall - elapsed) > 5:
        flags.append("wall_clock_jump")
    before = previous["probe"].get("health", {}).get("uptime")
    after = current["probe"].get("health", {}).get("uptime")
    if before is not None and after is not None and after < before:
        flags.append("core_restart")
    return flags


def run(url, output, *, samples=1, interval=60, pid=None, cgroup=None):
    endpoint = local_endpoint(url)
    if not 1 <= samples <= MAX_SAMPLES or not 1 <= interval <= 3600:
        raise ProbeError("INVALID_SAMPLE_BUDGET")
    if pid is not None and pid <= 0:
        raise ProbeError("INVALID_PID")
    output = output.absolute()
    if output.parent.resolve() != output.parent or output.is_symlink():
        raise ProbeError("UNSAFE_OUTPUT")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = output.parent.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise ProbeError("OUTPUT_DIRECTORY_MUST_BE_PRIVATE")
    if cgroup is not None:
        cgroup = cgroup.absolute()
        if (
            cgroup.resolve() != cgroup
            or not cgroup.is_relative_to("/sys/fs/cgroup")
            or not cgroup.is_dir()
        ):
            raise ProbeError("INVALID_CGROUP")
    root = process_info(pid) if pid else None
    if pid and root is None:
        raise ProbeError("MONITORED_PROCESS_UNAVAILABLE")
    model = Path("/sys/firmware/devicetree/base/model")
    is_pi = model.exists() and read_limited(model, 128).startswith("Raspberry Pi 5 Model B")
    kind = "raspberry_pi_5" if is_pi and platform.machine() == "aarch64" else "development_host"
    summary = {
        "samples": 0,
        "health_ok": 0,
        "health_degraded": 0,
        "errors": 0,
        "discontinuities": 0,
        "hardware_acceptance": False,
        "platform": kind,
        "stopped_for": "sample_budget",
        "elapsed_seconds": 0.0,
    }
    started = time.monotonic()
    previous = None
    written = 0
    if shutil.disk_usage(output.parent).free < RESERVE + MAX_BYTES:
        raise ProbeError("DISK_RESERVE")
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as file:

        def write(data):
            nonlocal written
            payload = json.dumps(data, separators=(",", ":")).encode() + b"\n"
            if len(payload) > 1536 or written + len(payload) > MAX_BYTES:
                raise ProbeError("OUTPUT_LIMIT")
            file.write(payload)
            file.flush()
            written += len(payload)

        write(
            {
                "type": "metadata",
                "version": 1,
                "platform": kind,
                "requested_samples": samples,
                "interval_seconds": interval,
                "hardware_acceptance": False,
                "raw_data": False,
                "auth": False,
            }
        )
        try:
            for sequence in range(samples):
                if sequence:
                    time.sleep(max(0, started + sequence * interval - time.monotonic()))
                if shutil.disk_usage(output.parent).free < RESERVE:
                    raise ProbeError("DISK_RESERVE")
                host = host_metrics()
                if host["MemAvailable"] < 64 * 1024**2:
                    raise ProbeError("SHARED_RAM_RESERVE")
                sample = {
                    "type": "sample",
                    "sequence": sequence,
                    "utc": datetime.now(UTC).isoformat(),
                    "unix": time.time(),
                    "elapsed": round(time.monotonic() - started, 3),
                    "host": host,
                    "family": family_metrics(pid, root["start"]) if pid else None,
                    "cgroup": cgroup_metrics(cgroup),
                    "probe": fetch_health(endpoint),
                }
                sample["discontinuities"] = discontinuities(previous, sample, interval)
                write(sample)
                summary["samples"] += 1
                status = sample["probe"].get("health", {}).get("status")
                key = (
                    "health_ok"
                    if status == "ok"
                    else "health_degraded"
                    if status == "degraded"
                    else "errors"
                )
                summary[key] += 1
                summary["discontinuities"] += len(sample["discontinuities"])
                summary["elapsed_seconds"] = sample["elapsed"]
                previous = sample
        except ProbeError as exc:
            summary["stopped_for"] = str(exc)
        except KeyboardInterrupt:
            summary["stopped_for"] = "interrupted"
        write({"type": "summary", **summary})
        os.fsync(file.fileno())
    return summary


def main():
    parser = argparse.ArgumentParser(description="Метрики локальной приёмки, без аппаратного PASS")
    parser.add_argument("--url", required=True, help="Только числовой LAN IP /api/v1/health")
    parser.add_argument(
        "--output", type=Path, required=True, help="Новый JSONL в закрытом каталоге700"
    )
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--pid", type=int, help="Свой PID Core; RSS с детьми≤128, без argv/env")
    parser.add_argument("--cgroup", type=Path, help="Явный каталог cgroup v2 службы Core")
    args = parser.parse_args()
    try:
        result = run(
            args.url,
            args.output,
            samples=args.samples,
            interval=args.interval,
            pid=args.pid,
            cgroup=args.cgroup,
        )
    except (ProbeError, OSError, ValueError):
        parser.exit(
            1, "Сбор не начат или прерван: проверьте локальный URL/ресурсы/новый закрытый путь\n"
        )
    print(json.dumps(result))
    if result["stopped_for"] != "sample_budget":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
