import asyncio
import json
import logging
import os
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.core.config import settings
from app.services.llm.protocol import (
    ERRORS,
    MAX_FRAME,
    MAX_MODEL_BYTES,
    Completion,
    GenerateRequest,
    LoadInfo,
    LoadRequest,
)

CORE = Path(__file__).resolve().parents[3]
logger = logging.getLogger("shade")


class LLMError(Exception):
    def __init__(self, code: str):
        self.code = code if code in ERRORS else "LLM_BAD_RESPONSE"
        super().__init__(self.code)


@dataclass(frozen=True)
class EngineConfig:
    enabled: bool
    model_path: str
    n_ctx: int
    n_threads: int
    max_tokens: int
    memory_limit_mb: int
    load_timeout: float
    inference_timeout: float

    @classmethod
    def current(cls):
        return cls(
            settings.llm_enabled,
            str(Path(settings.llm_model_path).resolve()),
            settings.llm_context_size,
            settings.llm_threads,
            settings.llm_max_tokens,
            settings.llm_memory_limit_mb,
            settings.llm_load_timeout_seconds,
            settings.llm_inference_timeout_seconds,
        )


class LocalLLMEngine:
    def __init__(self, config: EngineConfig | None = None):
        self.config = config or EngineConfig.current()
        self.status = "not_loaded"
        self.info: LoadInfo | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.closed = False
        self.load_task: asyncio.Task | None = None

    def start(self) -> None:
        if self.config.enabled:
            self.load_task = asyncio.create_task(self.background_load(), name="llm-load")

    async def background_load(self) -> None:
        try:
            await self.load()
        except LLMError as exc:
            logger.warning("LLM %s", exc.code)

    async def stop_process(self) -> None:
        process, self.process = self.process, None
        self.info = None
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 2)
        except TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()

    async def close(self) -> None:
        self.closed = True
        if self.load_task and not self.load_task.done():
            self.load_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.load_task
        await self.stop_process()
        self.status = "not_loaded"

    async def spawn(self) -> None:
        # Не наследовать API/HA-ключи, прокси, PYTHONPATH и пользовательские пакеты Core.
        environment = {
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "PYTHONUTF8": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str(CORE),
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": str(self.config.n_threads),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        creation = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.services.llm.runner",
                cwd=CORE,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=MAX_FRAME,
            )
        )
        try:
            self.process = await asyncio.shield(creation)
        except asyncio.CancelledError:
            self.process = await creation
            await self.stop_process()
            raise
        if self.closed:
            await self.stop_process()
            raise LLMError("LLM_CLOSED")

    async def exchange(self, request, timeout: float) -> dict:
        process = self.process
        if not process or process.returncode is not None:
            raise LLMError("LLM_PROCESS_EXITED")
        payload = request.model_dump_json(by_alias=True).encode("utf-8") + b"\n"
        if len(payload) > MAX_FRAME:
            raise LLMError("LLM_BAD_RESPONSE")
        try:
            async with asyncio.timeout(timeout):
                process.stdin.write(payload)
                await process.stdin.drain()
                line = await process.stdout.readline()
            if not line:
                raise LLMError("LLM_PROCESS_EXITED")
            if len(line) > MAX_FRAME or not line.endswith(b"\n"):
                raise LLMError("LLM_BAD_RESPONSE")
            response = json.loads(line)
            if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                raise LLMError("LLM_BAD_RESPONSE")
            if not response["ok"]:
                raise LLMError(response.get("error", "LLM_BAD_RESPONSE"))
            return response["result"]
        except TimeoutError:
            raise LLMError("LLM_TIMEOUT") from None
        except (ValueError, UnicodeError, KeyError, TypeError, RecursionError):
            raise LLMError("LLM_BAD_RESPONSE") from None
        except (OSError, RuntimeError):
            raise LLMError("LLM_PROCESS_EXITED") from None

    async def load(self) -> LoadInfo:
        if self.closed:
            raise LLMError("LLM_CLOSED")
        if not self.config.enabled:
            raise LLMError("LLM_DISABLED")
        if self.lock.locked():
            raise LLMError("LLM_BUSY")
        async with self.lock:
            if self.process and self.process.returncode is None and self.info:
                return self.info
            self.status = "loading"
            try:
                path = Path(self.config.model_path)
                if not path.is_file():
                    raise LLMError("LLM_MODEL_MISSING")
                if path.stat().st_size > MAX_MODEL_BYTES:
                    raise LLMError("LLM_MODEL_TOO_LARGE")
                with path.open("rb") as source:
                    if source.read(4) != b"GGUF":
                        raise LLMError("LLM_MODEL_INVALID")
                await self.stop_process()
                await self.spawn()
                try:
                    result = await self.exchange(
                        LoadRequest(
                            model_path=self.config.model_path,
                            n_ctx=self.config.n_ctx,
                            n_threads=self.config.n_threads,
                            memory_limit_mb=self.config.memory_limit_mb,
                        ),
                        self.config.load_timeout,
                    )
                except LLMError as exc:
                    if exc.code == "LLM_TIMEOUT":
                        raise LLMError("LLM_LOAD_TIMEOUT") from None
                    raise
                self.info = LoadInfo.model_validate(result)
                self.status = "ready"
                return self.info
            except asyncio.CancelledError:
                await self.stop_process()
                self.status = "LLM_CANCELLED"
                raise
            except (LLMError, ValidationError, OSError) as exc:
                await self.stop_process()
                code = exc.code if isinstance(exc, LLMError) else "LLM_BAD_RESPONSE"
                self.status = code
                raise LLMError(code) from None

    async def generate(self, messages: list[dict], *, schema: dict | None = None) -> Completion:
        if self.closed:
            raise LLMError("LLM_CLOSED")
        if self.status != "ready":
            raise LLMError(self.status if self.status in ERRORS else "LLM_NOT_READY")
        if self.lock.locked():
            raise LLMError("LLM_BUSY")
        try:
            request = GenerateRequest.model_validate(
                {
                    "messages": messages,
                    "max_tokens": self.config.max_tokens,
                    "schema": schema,
                }
            )
        except ValidationError:
            raise LLMError("LLM_BAD_RESPONSE") from None
        async with self.lock:
            try:
                result = await self.exchange(request, self.config.inference_timeout)
                return Completion.model_validate(result)
            except asyncio.CancelledError:
                await self.stop_process()
                self.status = "LLM_CANCELLED"
                raise
            except (LLMError, ValidationError) as exc:
                code = exc.code if isinstance(exc, LLMError) else "LLM_BAD_RESPONSE"
                if code != "LLM_CONTEXT_EXCEEDED":
                    await self.stop_process()
                    self.status = code
                raise LLMError(code) from None
