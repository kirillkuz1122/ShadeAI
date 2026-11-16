"""Ограниченный offline native-стенд на общем компьютере, без установки assets."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
GIB = 1024**3


def available_ram():
    return (
        int(
            next(
                line.split()[1]
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemAvailable:")
            )
        )
        * 1024
    )


def stop_group(child):
    # Группа включает stdio native-child; чужие процессы в неё не входят.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()


def run(command, seconds):
    disk, ram = shutil.disk_usage(CORE).free, available_ram()
    if disk < 4 * GIB or ram < 4 * GIB:
        raise RuntimeError("Нужны минимум4GiB диска и4GiB MemAvailable до native-старта")
    started = time.monotonic()
    minimum_disk, minimum_ram = disk, ram
    child = subprocess.Popen(["unshare", "-Urn", *command], start_new_session=True)
    reason = None
    try:
        while child.poll() is None:
            try:
                disk, ram = shutil.disk_usage(CORE).free, available_ram()
            except (OSError, ValueError, StopIteration):
                reason = "RESOURCE_PROBE_FAILED"
                break
            minimum_disk, minimum_ram = min(minimum_disk, disk), min(minimum_ram, ram)
            if disk < 4 * GIB:
                reason = "DISK_RESERVE"
            elif ram < GIB:
                reason = "RAM_RESERVE"
            elif time.monotonic() - started >= seconds:
                reason = "TIME_BUDGET"
            if reason:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        reason = "INTERRUPTED"
    finally:
        stop_group(child)
    return {
        "offline_network_namespace": True,
        "platform": "development-computer",
        "hardware_acceptance": False,
        "native_exit_code": child.returncode,
        "stopped_for": reason,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "minimum_free_bytes": minimum_disk,
        "minimum_available_ram_bytes": minimum_ram,
        "start_disk_ram_bytes": [4 * GIB, 4 * GIB],
        "stop_disk_ram_bytes": [4 * GIB, GIB],
        "time_budget_seconds": seconds,
    }


def interrupt(_signum, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seconds", type=int, choices=range(30, 901), default=600, metavar="30..900"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Нужна команда существующего native-стенда после --")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve файла до старта: прежний отчёт нельзя затереть даже при ошибке старта.
    with args.output.open("x") as destination:
        previous = signal.signal(signal.SIGTERM, interrupt)
        try:
            report = run(command, args.seconds)
        except (OSError, ValueError, StopIteration, RuntimeError):
            report = {"started": False, "error": "NATIVE_PREFLIGHT_FAILED"}
            destination.write(json.dumps(report) + "\n")
            raise SystemExit(2) from None
        finally:
            signal.signal(signal.SIGTERM, previous)
        destination.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    raise SystemExit(75 if report["stopped_for"] else report["native_exit_code"])


if __name__ == "__main__":
    main()
