"""Резервы AVD проверяются до запуска процесса, без SDK/KVM/эмулятора."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def guard(monkeypatch):
    path = Path(__file__).with_name("run_emulator_guarded.py")
    spec = importlib.util.spec_from_file_location("shade_avd_guard_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "argv", [str(path)])
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_a, **_k: pytest.fail("AVD запущен"))
    return module


@pytest.mark.parametrize("disk,ram", [(5, 4), (8, 2)])
def test_insufficient_disk_or_ram_never_starts_avd(guard, monkeypatch, disk, ram):
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _p: SimpleNamespace(free=disk * 1024**3))
    monkeypatch.setattr(guard, "ram", lambda: ram * 1024**3)
    with pytest.raises(SystemExit, match="6 GiB диска и 3 GiB"):
        guard.main()


def test_longer_unbounded_session_rejected_before_resource_access(guard, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["guard", "--minutes", "26"])
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _p: pytest.fail("Резервы прочитаны"))
    with pytest.raises(SystemExit) as error:
        guard.main()
    assert error.value.code == 2
