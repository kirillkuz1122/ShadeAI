import asyncio
import hashlib
import json

import pytest

from app.core.config import settings
from app.services.voice import engine as module
from app.services.voice.engine import STTEngine
from app.services.voice.errors import VoiceError
from app.services.voice.model_manifest import MANIFEST, inventory, validate


def engine(tmp_path, monkeypatch, script):
    worker = tmp_path / "synthetic_stt.py"
    worker.write_text(script)
    monkeypatch.setattr(settings, "voice_model_path", str(tmp_path))
    monkeypatch.setattr(settings, "voice_model_manifest_sha256", "a" * 64)
    monkeypatch.setattr(settings, "voice_memory_limit_mb", 256)
    monkeypatch.setattr(settings, "voice_timeout_seconds", 5)
    monkeypatch.setattr(module, "available_memory", lambda: 2 * 1024**3)
    value = STTEngine()
    value.worker = worker
    value.configured = lambda: True
    return value


def test_synthetic_child_protocol_and_environment_without_native_speech(tmp_path, monkeypatch):
    script = """import json,os,sys
header=json.loads(sys.stdin.buffer.readline())
audio=sys.stdin.buffer.read()
assert len(audio)==header['audio_size']
assert not {'SHADE_API_KEY','HA_TOKEN','HTTP_PROXY','HTTPS_PROXY','PYTHONPATH'} & os.environ.keys()
reply={'text':'синтетический ответ','confidence':.99,'peak_rss_kib':1024}
print(json.dumps(reply,ensure_ascii=False))
"""
    monkeypatch.setenv("HTTP_PROXY", "private-proxy")
    value = engine(tmp_path, monkeypatch, script)

    async def scenario():
        result = await value.transcribe(b"x" * 44)
        assert (
            result.text == "синтетический ответ"
            and result.confidence == 0.99
            and value.process is None
        )
        await value.close()
        with pytest.raises(VoiceError, match="STT_CLOSED"):
            await value.transcribe(b"x" * 44)

    asyncio.run(scenario())


def test_busy_and_cancel_reap_only_child(tmp_path, monkeypatch):
    value = engine(
        tmp_path, monkeypatch, "import sys,time\nsys.stdin.buffer.read()\ntime.sleep(30)\n"
    )

    async def scenario():
        task = asyncio.create_task(value.transcribe(b"x" * 44))
        for _ in range(100):
            if value.process is not None:
                break
            await asyncio.sleep(0.005)
        process = value.process
        assert process is not None
        with pytest.raises(VoiceError, match="STT_BUSY"):
            await value.transcribe(b"x" * 44)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.returncode is not None and value.process is None
        await value.close()

    asyncio.run(scenario())


def test_timeout_and_shared_memory_reserve(tmp_path, monkeypatch):
    value = engine(
        tmp_path, monkeypatch, "import sys,time\nsys.stdin.buffer.read()\ntime.sleep(30)\n"
    )
    monkeypatch.setattr(settings, "voice_timeout_seconds", 0.2)

    async def scenario():
        with pytest.raises(VoiceError, match="STT_TIMEOUT"):
            await value.transcribe(b"x" * 44)
        assert value.process is None
        monkeypatch.setattr(module, "available_memory", lambda: 0)
        with pytest.raises(VoiceError, match="STT_RESOURCE_LIMIT"):
            await value.transcribe(b"x" * 44)
        assert value.process is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "packet",
    [
        "private-native-garbage",
        '{"text":"hello","confidence":NaN,"peak_rss_kib":1}',
        json.dumps(dict(text="hello", confidence=True, peak_rss_kib=1)),
        json.dumps(dict(text="hello", confidence=0.2, peak_rss_kib=1)),
    ],
)
def test_untrusted_child_output_is_bounded_and_does_not_echo(packet, tmp_path, monkeypatch):
    value = engine(
        tmp_path, monkeypatch, "import sys\nsys.stdin.buffer.read()\nprint(" + repr(packet) + ")\n"
    )

    async def scenario():
        with pytest.raises(VoiceError) as error:
            await value.transcribe(b"x" * 44)
        assert error.value.code in {
            "STT_BAD_RESPONSE",
            "VOICE_UNRECOGNIZED",
        } and "private" not in str(error.value)
        assert value.process is None

    asyncio.run(scenario())


def test_manifest_detects_changed_files_extra_files_and_symlinks(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    (root / "weights.bin").write_bytes(b"synthetic model")
    data = json.dumps(
        dict(version=1, files=inventory(root)), sort_keys=True, separators=(",", ":")
    ).encode()
    (root / MANIFEST).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    validate(root, digest)
    (root / "weights.bin").write_bytes(b"changed")
    with pytest.raises(ValueError):
        validate(root, digest)
    (root / "weights.bin").write_bytes(b"synthetic model")
    (root / "extra.bin").write_bytes(b"extra")
    with pytest.raises(ValueError):
        validate(root, digest)
    (root / "extra.bin").unlink()
    (root / "link").symlink_to(root / "weights.bin")
    with pytest.raises(ValueError):
        inventory(root)
