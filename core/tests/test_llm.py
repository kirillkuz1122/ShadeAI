import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.services.llm.engine import EngineConfig, LLMError, LocalLLMEngine
from app.services.llm.protocol import MAX_MODEL_BYTES, ChatMessage, GenerateRequest

PRIVATE = "private-llm-input-839174"
MESSAGES = [{"role": "user", "content": "Синтетическая проверка"}]
LOAD = {
    "sha256": "a" * 64,
    "model_bytes": 8,
    "load_ms": 1.0,
    "peak_rss_bytes": 1024,
    "n_ctx": 1024,
    "n_threads": 2,
}
RESULT = {
    "content": '{"answer":"ok"}',
    "finish_reason": "stop",
    "prompt_tokens": 5,
    "completion_tokens": 4,
    "inference_ms": 1.0,
    "peak_rss_bytes": 2048,
}


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.stdout = asyncio.StreamReader(limit=65_536)
        self.stdin = self
        self.exited = asyncio.Event()
        self.requests = []
        self.hang = None
        self.bad = None
        self.terminated = False
        self.stdin_closed = False

    def write(self, raw):
        request = json.loads(raw)
        self.requests.append(request)
        if self.hang == request["op"]:
            return
        if self.bad is not None:
            self.stdout.feed_data(self.bad)
            return
        result = LOAD if request["op"] == "load" else RESULT
        self.stdout.feed_data(json.dumps({"ok": True, "result": result}).encode() + b"\n")

    async def drain(self):
        pass

    def close(self):
        self.stdin_closed = True

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self.exited.set()
        self.stdout.feed_eof()

    def kill(self):
        self.terminate()
        self.returncode = -9

    async def wait(self):
        await self.exited.wait()
        return self.returncode


@pytest.fixture
def configuration(tmp_path):
    model = tmp_path / "synthetic.gguf"
    model.write_bytes(b"GGUFfake")
    return EngineConfig(True, str(model), 1024, 2, 128, 2304, 0.05, 0.05)


@pytest.fixture
def processes(monkeypatch):
    output, options = [], []

    async def spawn(*args, **kwargs):
        process = FakeProcess()
        output.append(process)
        options.append((args, kwargs))
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return output, options


@pytest.mark.asyncio
async def test_disabled_and_missing_model_do_not_spawn(configuration, processes):
    disabled = LocalLLMEngine(replace(configuration, enabled=False))
    with pytest.raises(LLMError, match="LLM_DISABLED"):
        await disabled.load()
    missing = LocalLLMEngine(replace(configuration, model_path="missing.gguf"))
    with pytest.raises(LLMError, match="LLM_MODEL_MISSING"):
        await missing.load()
    assert not processes[0]


@pytest.mark.asyncio
async def test_bad_and_oversized_model_rejected_before_spawn(configuration, processes):
    path = Path(configuration.model_path)
    path.write_bytes(b"invalid")
    engine = LocalLLMEngine(configuration)
    with pytest.raises(LLMError, match="LLM_MODEL_INVALID"):
        await engine.load()
    with path.open("wb") as file:
        file.truncate(MAX_MODEL_BYTES + 1)
    with pytest.raises(LLMError, match="LLM_MODEL_TOO_LARGE"):
        await engine.load()
    assert processes[0] == []


@pytest.mark.asyncio
async def test_load_generate_serial_protocol_and_private_environment(
    configuration, processes, monkeypatch
):
    monkeypatch.setenv("SECRET_TEST", PRIVATE)
    monkeypatch.setenv("HTTP_PROXY", "http://external.invalid")
    engine = LocalLLMEngine(configuration)
    info = await engine.load()
    assert info.n_ctx == 1024 and engine.status == "ready"
    assert (await engine.load()) is info and len(processes[0]) == 1
    result = await engine.generate(MESSAGES, schema={"type": "object"})
    assert result.content == RESULT["content"] and result.completion_tokens == 4
    environment = processes[1][0][1]["env"]
    assert "SECRET_TEST" not in environment and "SHADE_API_KEY" not in environment
    assert "HA_TOKEN" not in environment and "HTTP_PROXY" not in environment
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert processes[0][0].requests[1]["schema"] == {"type": "object"}
    await engine.close()
    await engine.close()
    assert processes[0][0].terminated and engine.process is None
    with pytest.raises(LLMError, match="LLM_CLOSED"):
        await engine.generate(MESSAGES)


@pytest.mark.asyncio
async def test_generation_timeout_kills_and_allows_explicit_reload(configuration, processes):
    engine = LocalLLMEngine(configuration)
    await engine.load()
    processes[0][0].hang = "generate"
    with pytest.raises(LLMError, match="LLM_TIMEOUT"):
        await engine.generate(MESSAGES)
    assert processes[0][0].terminated and engine.process is None
    await engine.load()
    assert len(processes[0]) == 2 and engine.status == "ready"
    await engine.close()


@pytest.mark.asyncio
async def test_load_timeout_is_distinct(configuration, monkeypatch):
    process = FakeProcess()
    process.hang = "load"

    async def spawn(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    engine = LocalLLMEngine(configuration)
    with pytest.raises(LLMError, match="LLM_LOAD_TIMEOUT"):
        await engine.load()
    assert process.terminated and engine.status == "LLM_LOAD_TIMEOUT"


@pytest.mark.asyncio
async def test_concurrency_and_cancellation_kill_inflight(configuration, processes):
    engine = LocalLLMEngine(configuration)
    await engine.load()
    processes[0][0].hang = "generate"
    running = asyncio.create_task(engine.generate(MESSAGES))
    await asyncio.sleep(0)
    with pytest.raises(LLMError, match="LLM_BUSY"):
        await engine.generate(MESSAGES)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert processes[0][0].terminated and engine.status == "LLM_CANCELLED"
    await engine.close()


@pytest.mark.asyncio
async def test_cancel_spawn_does_not_leak_process(configuration, monkeypatch):
    process = FakeProcess()
    gate, entered = asyncio.Event(), asyncio.Event()

    async def spawn(*args, **kwargs):
        entered.set()
        await gate.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    engine = LocalLLMEngine(configuration)
    running = asyncio.create_task(engine.load())
    await entered.wait()
    running.cancel()
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert process.terminated and engine.process is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        b"[]\n",
        b"{broken}\n",
        b'{"ok":true,"result":{"raw":"private"}}\n',
        b'{"ok":false,"error":{"raw":"private"}}\n',
        b"x" * 70_000 + b"\n",
    ],
)
async def test_bad_child_response_is_safe_and_fatal(configuration, processes, reply):
    engine = LocalLLMEngine(configuration)
    await engine.load()
    processes[0][0].bad = reply
    with pytest.raises(LLMError, match="LLM_BAD_RESPONSE") as caught:
        await engine.generate([{"role": "user", "content": PRIVATE}])
    assert PRIVATE not in str(caught.value)
    assert processes[0][0].terminated


@pytest.mark.asyncio
async def test_context_error_keeps_valid_model(configuration, processes):
    engine = LocalLLMEngine(configuration)
    await engine.load()
    process = processes[0][0]
    process.bad = b'{"ok":false,"error":"LLM_CONTEXT_EXCEEDED"}\n'
    with pytest.raises(LLMError, match="LLM_CONTEXT_EXCEEDED"):
        await engine.generate(MESSAGES)
    assert not process.terminated and engine.status == "ready"
    process.bad = None
    assert (await engine.generate(MESSAGES)).content
    await engine.close()


@pytest.mark.asyncio
async def test_eof_and_missing_dependency_are_distinct(configuration, processes):
    engine = LocalLLMEngine(configuration)
    await engine.load()
    process = processes[0][0]
    process.terminate()
    with pytest.raises(LLMError, match="LLM_PROCESS_EXITED"):
        await engine.generate(MESSAGES)
    assert engine.process is None


@pytest.fixture
def enabled_missing(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)


@pytest.fixture
def missing_client(enabled_missing, client):
    return client


def test_core_works_without_model(missing_client, auth_headers):
    client = missing_client

    async def wait_error():
        async with asyncio.timeout(1):
            while client.app.state.llm.status == "loading":
                await asyncio.sleep(0.005)

    client.portal.call(wait_error)
    body = client.get("/api/v1/health").json()
    assert body["llm_status"] == "LLM_MODEL_MISSING" and body["db_connected"]
    assert client.get("/api/v1/notifications", headers=auth_headers).status_code == 200
    assert (
        client.post(
            "/api/v1/devices/light.test/command", headers=auth_headers, json={"action": "turn_on"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("value", [0, 5])
def test_thread_bounds(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_threads=value)


def test_message_size_and_extra_fields():
    with pytest.raises(ValidationError):
        ChatMessage(role="tool", content="text")
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="text", key=PRIVATE)
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate(
            {"messages": [{"role": "user", "content": "Ж" * 8192}] * 3, "max_tokens": 128}
        )
