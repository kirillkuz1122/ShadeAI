from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FRAME = 65_536
MAX_MODEL_BYTES = 2 * 1024**3
ERRORS = {
    "LLM_DISABLED",
    "LLM_NOT_READY",
    "LLM_BUSY",
    "LLM_CLOSED",
    "LLM_CANCELLED",
    "LLM_MODEL_MISSING",
    "LLM_MODEL_INVALID",
    "LLM_MODEL_TOO_LARGE",
    "LLM_DEPENDENCY_MISSING",
    "LLM_MEMORY_LIMIT",
    "LLM_LOAD_FAILED",
    "LLM_LOAD_TIMEOUT",
    "LLM_TIMEOUT",
    "LLM_INFERENCE_FAILED",
    "LLM_CONTEXT_EXCEEDED",
    "LLM_BAD_RESPONSE",
    "LLM_PROCESS_EXITED",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class ChatMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=8192)


class LoadRequest(StrictModel):
    op: Literal["load"] = "load"
    model_path: str = Field(min_length=1, max_length=4096)
    n_ctx: int = Field(ge=256, le=2048)
    n_threads: int = Field(ge=1, le=4)
    memory_limit_mb: int = Field(ge=512, le=2560)


class GenerateRequest(StrictModel):
    op: Literal["generate"] = "generate"
    messages: list[ChatMessage] = Field(min_length=1, max_length=8)
    max_tokens: int = Field(ge=1, le=256)
    schema_: dict | None = Field(default=None, alias="schema")

    @model_validator(mode="after")
    def bound_messages(self):
        if sum(len(item.content.encode("utf-8")) for item in self.messages) > 32_768:
            raise ValueError("Превышен размер текста")
        return self


class Completion(StrictModel):
    content: str = Field(max_length=16_384)
    finish_reason: Literal["stop", "length"]
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0, le=256)
    inference_ms: float = Field(ge=0, allow_inf_nan=False)
    peak_rss_bytes: int = Field(ge=0)


class LoadInfo(StrictModel):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_bytes: int = Field(ge=1, le=MAX_MODEL_BYTES)
    load_ms: float = Field(ge=0, allow_inf_nan=False)
    peak_rss_bytes: int = Field(ge=0)
    n_ctx: int = Field(ge=256, le=2048)
    n_threads: int = Field(ge=1, le=4)
