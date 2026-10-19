"""Одноразовый read-only AVD из существующего SDK, с резервом общего диска/RAM."""

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

ANDROID = Path(__file__).resolve().parents[1]


def ram():
    return (
        int(
            next(
                s
                for s in Path("/proc/meminfo").read_text().splitlines()
                if s.startswith("MemAvailable:")
            ).split()[1]
        )
        * 1024
    )


def main():
    if shutil.disk_usage(ANDROID).free < 6 * 1024**3 or ram() < 3 * 1024**3:
        raise SystemExit("Для стенда нужны 6 GiB диска и 3 GiB доступной RAM")
    if not os.access("/dev/kvm", os.W_OK):
        raise SystemExit("Нужно уже доступное KVM; программную эмуляцию не запускаем")
    env = dict(
        os.environ,
        ANDROID_AVD_HOME=str(ANDROID / ".gradle/avd"),
        ANDROID_USER_HOME=str(ANDROID / ".gradle/android-home"),
        ANDROID_HOME=str(ANDROID / ".gradle/sdk"),
    )
    command = [
        str(ANDROID / ".gradle/sdk/emulator/emulator"),
        "-avd",
        "ShadeTask03API35",
        "-port",
        "5554",
        "-read-only",
        "-no-window",
        "-no-snapshot",
        "-no-boot-anim",
        "-noaudio",
        "-memory",
        "1536",
        "-cores",
        "2",
        "-gpu",
        "swiftshader_indirect",
    ]
    with (ANDROID / ".gradle/task24-emulator.log").open("w") as log:
        child = subprocess.Popen(
            command,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + 900
        try:
            while child.poll() is None:
                free, available = shutil.disk_usage(ANDROID).free, ram()
                reason = (
                    "DISK_RESERVE"
                    if free < 4 * 1024**3
                    else "RAM_RESERVE"
                    if available < 1024**3
                    else "TIME_BUDGET"
                    if time.monotonic() > deadline
                    else None
                )
                if reason:
                    print(
                        json.dumps(
                            dict(stopped_for=reason, free_bytes=free, available_ram_bytes=available)
                        ),
                        flush=True,
                    )
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            print("Останавливаем собственный read-only AVD", flush=True)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        print(
            f"AVD завершён, код {child.returncode}; чужие процессы не останавливались",
            flush=True,
        )


if __name__ == "__main__":
    main()
