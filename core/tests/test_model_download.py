import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/download_model.py"
DATA = b"GGUF-synthetic-model"


@pytest.fixture
def downloader(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("shade_download_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3))
    (tmp_path / "scripts").mkdir()
    (tmp_path / "models").mkdir()
    (tmp_path / "scripts/models.json").write_text(
        json.dumps(
            {
                "qwen": {
                    "repo": "synthetic/model",
                    "revision": "a" * 40,
                    "file": "model.gguf",
                    "bytes": len(DATA),
                    "sha256": hashlib.sha256(DATA).hexdigest(),
                }
            }
        )
    )
    calls = []

    class Response(io.BytesIO):
        status = 200
        headers = {}

    def response(request, timeout):
        calls.append(request)
        return Response(DATA)

    monkeypatch.setattr(module.urllib.request, "urlopen", response)
    return module, calls, Response


def target(module):
    return module.ROOT / "core/models/model.gguf"


def test_valid_download_is_atomic_and_existing_good_file_is_reused(downloader):
    module, calls, _ = downloader
    (module.ROOT / "core").mkdir()
    module.download("qwen")
    assert target(module).read_bytes() == DATA and len(calls) == 1
    module.download("qwen")
    assert len(calls) == 1
    assert not target(module).with_suffix(".gguf.part").exists()
    assert "/resolve/" + "a" * 40 + "/model.gguf" in calls[0].full_url


@pytest.mark.parametrize("resume", [True, False])
def test_resume_range_or_restart_when_server_ignores_range(downloader, monkeypatch, resume):
    module, _, Response = downloader
    (module.ROOT / "core/models").mkdir(parents=True)
    partial = target(module).with_suffix(".gguf.part")
    partial.write_bytes(DATA[:4])

    def response(request, timeout):
        assert request.get_header("Range") == "bytes=4-"
        result = Response(DATA[4:] if resume else DATA)
        result.status = 206 if resume else 200
        result.headers = {"Content-Range": f"bytes 4-{len(DATA) - 1}/{len(DATA)}"} if resume else {}
        return result

    monkeypatch.setattr(module.urllib.request, "urlopen", response)
    module.download("qwen")
    assert target(module).read_bytes() == DATA


def test_full_partial_verified_without_new_request(downloader):
    module, calls, _ = downloader
    (module.ROOT / "core/models").mkdir(parents=True)
    target(module).with_suffix(".gguf.part").write_bytes(DATA)
    module.download("qwen")
    assert target(module).read_bytes() == DATA and not calls


@pytest.mark.parametrize("data", [b"x" * len(DATA), DATA + b"extra"])
def test_bad_download_does_not_replace_existing_file(downloader, monkeypatch, data):
    module, _, Response = downloader
    (module.ROOT / "core/models").mkdir(parents=True)
    target(module).write_bytes(b"previous-corrupt-file")
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: Response(data))
    with pytest.raises(RuntimeError):
        module.download("qwen")
    assert target(module).read_bytes() == b"previous-corrupt-file"


def test_wrong_content_range_does_not_append(downloader, monkeypatch):
    module, _, Response = downloader
    (module.ROOT / "core/models").mkdir(parents=True)
    partial = target(module).with_suffix(".gguf.part")
    partial.write_bytes(DATA[:4])

    def response(*args, **kwargs):
        result = Response(DATA)
        result.status = 206
        result.headers = {"Content-Range": "bytes 1-9/20"}
        return result

    monkeypatch.setattr(module.urllib.request, "urlopen", response)
    with pytest.raises(RuntimeError, match="продолжение"):
        module.download("qwen")
    assert partial.read_bytes() == DATA[:4] and not target(module).exists()


def test_low_disk_blocks_request_without_removing_partial(downloader, monkeypatch):
    module, calls, _ = downloader
    (module.ROOT / "core/models").mkdir(parents=True)
    partial = target(module).with_suffix(".gguf.part")
    partial.write_bytes(DATA[:4])
    monkeypatch.setattr(
        module.shutil, "disk_usage", lambda _: SimpleNamespace(free=module.DISK_RESERVE_BYTES)
    )
    with pytest.raises(RuntimeError, match="4 GiB"):
        module.download("qwen")
    assert not calls and partial.read_bytes() == DATA[:4]


def test_disk_consumed_by_other_process_blocks_next_write(downloader, monkeypatch):
    module, _, _ = downloader
    (module.ROOT / "core/models").mkdir(parents=True)
    free = iter([10 * 1024**3, module.DISK_RESERVE_BYTES])
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=next(free)))
    with pytest.raises(RuntimeError, match="4 GiB"):
        module.download("qwen")
    assert not target(module).exists()
    assert target(module).with_suffix(".gguf.part").stat().st_size == 0


def test_already_downloaded_model_does_not_require_extra_space(downloader, monkeypatch):
    module, calls, _ = downloader
    (module.ROOT / "core/models").mkdir(parents=True)
    target(module).with_suffix(".gguf.part").write_bytes(DATA)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    module.download("qwen")
    module.download("qwen")
    assert target(module).read_bytes() == DATA and not calls
