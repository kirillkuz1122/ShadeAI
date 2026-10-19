import asyncio
import importlib.util
import json
import math
import os
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.services.voice.errors import VoiceError

RESERVE = 256 * 1024**2


def available_memory() -> int:
    available = 0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            available = int(line.split()[1]) * 1024
    try:
        limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if limit != "max":
            available = min(
                available, int(limit) - int(Path("/sys/fs/cgroup/memory.current").read_text())
            )
    except (OSError, ValueError):
        pass
    return max(0, available)


@dataclass(repr=False)
class Transcription:
    text: str
    confidence: float
    peak_rss_kib: int = 0


class STTEngine:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.process = None
        self.closed = False
        self.worker = Path(__file__).with_name("runner.py")
        self.last_peak_rss_kib = 0

    def configured(self):
        path = settings.voice_model_path
        return bool(
            path
            and settings.voice_model_manifest_sha256
            and Path(path).is_dir()
            and (Path(path) / "shade-model.json").is_file()
            and importlib.util.find_spec("vosk") is not None
        )

    async def terminate(self, process):
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 2)
        except TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()

    async def close(self):
        self.closed = True
        if self.process is not None:
            await self.terminate(self.process)

    async def transcribe(self, audio: bytes) -> Transcription:
        if self.closed:
            raise VoiceError("STT_CLOSED", 503)
        if self.lock.locked():
            raise VoiceError("STT_BUSY", 409)
        async with self.lock:
            if not self.configured():
                raise VoiceError("STT_NOT_CONFIGURED", 503)
            if available_memory() < settings.voice_memory_limit_mb * 1024**2 + RESERVE:
                raise VoiceError("STT_RESOURCE_LIMIT", 503)
            packet = (
                json.dumps(
                    dict(
                        model_path=str(Path(settings.voice_model_path).resolve()),
                        manifest_sha256=settings.voice_model_manifest_sha256,
                        memory_mb=settings.voice_memory_limit_mb,
                        timeout_seconds=settings.voice_timeout_seconds,
                        audio_size=len(audio),
                    )
                ).encode()
                + b"\n"
            )
            environment = dict(
                PATH=os.defpath,
                LANG="C.UTF-8",
                OMP_NUM_THREADS="1",
                OPENBLAS_NUM_THREADS="1",
                MKL_NUM_THREADS="1",
            )
            process, exchange = None, None
            creation = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    sys.executable,
                    "-I",
                    str(self.worker),
                    env=environment,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=8192,
                )
            )
            try:
                try:
                    process = await asyncio.shield(creation)
                except asyncio.CancelledError:
                    process = await creation
                    raise
                self.process = process
                if self.closed:
                    raise VoiceError("STT_CLOSED", 503)
                exchange = asyncio.create_task(process.communicate(packet + audio))
                deadline = asyncio.get_running_loop().time() + settings.voice_timeout_seconds
                while not exchange.done():
                    await asyncio.wait({exchange}, timeout=0.1)
                    if asyncio.get_running_loop().time() > deadline:
                        raise VoiceError("STT_TIMEOUT", 504)
                    if available_memory() < RESERVE:
                        raise VoiceError("STT_RESOURCE_LIMIT", 503)
                output, _ = await exchange
                if process.returncode != 0 or len(output) > 8192:
                    raise VoiceError("STT_FAILED", 503)
                value = json.loads(
                    output, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
                )
                if "error" in value:
                    raise VoiceError("STT_FAILED", 503)
                text, score, peak = value["text"], value["confidence"], value["peak_rss_kib"]
                if (
                    not isinstance(text, str)
                    or len(text) > 512
                    or type(score) not in {int, float}
                    or not math.isfinite(score)
                    or not 0 <= score <= 1
                    or type(peak) is not int
                    or not 0 <= peak <= settings.voice_memory_limit_mb * 1024
                ):
                    raise VoiceError("STT_BAD_RESPONSE", 503)
                self.last_peak_rss_kib = peak
                if not text or score < 0.8:
                    raise VoiceError("VOICE_UNRECOGNIZED")
                return Transcription(text, score, peak)
            except (OSError, ValueError, KeyError, TypeError):
                raise VoiceError("STT_BAD_RESPONSE", 503) from None
            finally:
                if process is not None:
                    await self.terminate(process)
                if exchange is not None and not exchange.done():
                    exchange.cancel()
                    with suppress(asyncio.CancelledError, BrokenPipeError, ConnectionResetError):
                        await exchange
                self.process = None
