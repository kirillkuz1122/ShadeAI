"""Сборка только из имеющегося кэша с резервом диска/RAM; без постоянного Gradle/Kotlin daemon."""

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

ANDROID = Path(__file__).resolve().parents[1]
RESERVE = 4 * 1024**3
MIN_RAM = 768 * 1024**2


def available_ram():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise SystemExit("Не удалось измерить доступную RAM")


def main():
    before = shutil.disk_usage(ANDROID).free
    if before < RESERVE + 2 * 1024**3 or available_ram() < 2 * 1024**3:
        raise SystemExit(
            "Недостаточный запас для offline Gradle: нужны 6 GiB диска/2 GiB RAM"
        )
    env = dict(os.environ)
    env.pop("ANDROID_SDK_ROOT", None)
    env.update(
        JAVA_HOME="/usr/lib/jvm/java-17-openjdk",
        ANDROID_HOME=str(ANDROID / ".gradle/sdk"),
        ANDROID_USER_HOME=str(ANDROID / ".gradle/android-home"),
        GRADLE_USER_HOME=str(ANDROID / ".gradle/user-home"),
    )
    command = [
        "./gradlew",
        ":app:assembleDebug",
        ":app:testDebugUnitTest",
        ":app:lintDebug",
        "--offline",
        "--no-daemon",
        "--max-workers=1",
        "--no-parallel",
        "-Dorg.gradle.jvmargs=-Xmx768m -Dfile.encoding=UTF-8",
        "-Pkotlin.compiler.execution.strategy=in-process",
    ]
    log = ANDROID / ".gradle/task23-offline-check.log"
    reason = None
    with log.open("w") as output:
        child = subprocess.Popen(
            command,
            cwd=ANDROID,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + 900
        while child.poll() is None:
            if shutil.disk_usage(ANDROID).free < RESERVE:
                reason = "DISK_RESERVE"
            elif available_ram() < MIN_RAM:
                reason = "SHARED_RAM_RESERVE"
            elif time.monotonic() > deadline:
                reason = "TIME_BUDGET"
            if reason:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                break
            time.sleep(1)
    print(
        json.dumps(
            {
                "exit_code": child.returncode,
                "stopped_for": reason,
                "free_before": before,
                "free_after": shutil.disk_usage(ANDROID).free,
                "log": str(log),
            }
        )
    )
    print("\n".join(log.read_text().splitlines()[-45:]))
    raise SystemExit(
        child.returncode
        if child.returncode and child.returncode > 0
        else 1
        if reason
        else 0
    )


if __name__ == "__main__":
    main()
