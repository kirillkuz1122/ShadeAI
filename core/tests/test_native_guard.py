from types import SimpleNamespace

import pytest

from checks import run_native_guarded as guard


@pytest.mark.parametrize(("disk", "ram"), [(3, 8), (8, 3)])
def test_native_does_not_start_without_shared_host_reserve(monkeypatch, disk, ram):
    monkeypatch.setattr(
        guard.shutil, "disk_usage", lambda _: SimpleNamespace(free=disk * guard.GIB)
    )
    monkeypatch.setattr(guard, "available_ram", lambda: ram * guard.GIB)
    monkeypatch.setattr(guard.subprocess, "Popen", lambda *a, **k: pytest.fail("child started"))
    with pytest.raises(RuntimeError):
        guard.run(["ignored"], 30)


@pytest.mark.parametrize(
    ("disk", "ram", "reason"),
    [
        (3, 8, "DISK_RESERVE"),
        (8, 0, "RAM_RESERVE"),
        (8, 8, "TIME_BUDGET"),
    ],
)
def test_pressure_or_deadline_stops_only_own_group(monkeypatch, disk, ram, reason):
    disks = iter([8 * guard.GIB, disk * guard.GIB])
    rams = iter([8 * guard.GIB, ram * guard.GIB])
    ticks = iter([0, 31, 32])
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _: SimpleNamespace(free=next(disks)))
    monkeypatch.setattr(guard, "available_ram", lambda: next(rams))
    monkeypatch.setattr(guard.time, "monotonic", lambda: next(ticks))
    child = SimpleNamespace(pid=123456, returncode=-15, poll=lambda: None)
    called = []

    def spawn(command, **kwargs):
        assert command == ["unshare", "-Urn", "native-check"]
        assert kwargs == {"start_new_session": True}
        return child

    monkeypatch.setattr(guard.subprocess, "Popen", spawn)
    monkeypatch.setattr(guard, "stop_group", lambda process: called.append(process))
    result = guard.run(["native-check"], 30)
    assert result["stopped_for"] == reason
    assert called == [child]
    assert result["hardware_acceptance"] is False


def test_existing_guard_report_prevents_start(monkeypatch, tmp_path):
    report = tmp_path / "guard.json"
    report.write_text("preserved")
    monkeypatch.setattr(guard, "run", lambda *a: pytest.fail("started"))
    monkeypatch.setattr("sys.argv", ["guard", "--output", str(report), "--", "native-check"])
    with pytest.raises(FileExistsError):
        guard.main()
    assert report.read_text() == "preserved"


@pytest.mark.parametrize("times_out", [False, True])
def test_stop_group_terminates_then_kills_descendants_and_reaps(monkeypatch, times_out):
    import signal
    import subprocess

    signals, waits = [], []

    def wait(timeout=None):
        waits.append(timeout)
        if times_out and timeout is not None:
            raise subprocess.TimeoutExpired("native", timeout)

    child = SimpleNamespace(pid=123456, wait=wait)
    monkeypatch.setattr(guard.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    guard.stop_group(child)
    assert signals == [(123456, signal.SIGTERM), (123456, signal.SIGKILL)]
    assert waits == [3, None]


def test_lost_resource_probe_stops_already_started_group(monkeypatch):
    calls = []

    def disk(_):
        if calls:
            raise OSError("probe unavailable")
        calls.append("preflight")
        return SimpleNamespace(free=8 * guard.GIB)

    child = SimpleNamespace(pid=123456, returncode=-15, poll=lambda: None)
    stopped = []
    monkeypatch.setattr(guard.shutil, "disk_usage", disk)
    monkeypatch.setattr(guard, "available_ram", lambda: 8 * guard.GIB)
    monkeypatch.setattr(guard.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(guard, "stop_group", lambda process: stopped.append(process))
    result = guard.run(["native-check"], 30)
    assert result["stopped_for"] == "RESOURCE_PROBE_FAILED"
    assert stopped == [child]
