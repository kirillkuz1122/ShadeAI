"""Закрытый stdin/stdout-протокол локального процесса; никаких HTTP/HF-загрузок."""

import hashlib
import json
import os
import resource
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from app.services.llm.protocol import MAX_FRAME, MAX_MODEL_BYTES, GenerateRequest, LoadRequest


def no_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise OSError("Network is disabled")


def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    sys.addaudithook(no_network)
    # Отдельный dup для RPC: Python/native stdout/stderr модели не могут утечь в протокол/логи.
    output = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    sink = open(os.devnull, "w")
    os.dup2(sink.fileno(), 1)
    os.dup2(sink.fileno(), 2)
    sys.stdout, sys.stderr = sink, sink
    model = None
    n_ctx = 0

    def reply(**body):
        raw = json.dumps(body, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        if len(raw.encode()) > MAX_FRAME:
            raw = '{"ok":false,"error":"LLM_BAD_RESPONSE"}'
        output.write(raw + "\n")

    while True:
        line = sys.stdin.buffer.readline(MAX_FRAME + 1)
        if not line:
            return
        if len(line) > MAX_FRAME or not line.endswith(b"\n"):
            reply(ok=False, error="LLM_BAD_RESPONSE")
            return
        try:
            command = json.loads(line)
            if not isinstance(command, dict):
                raise ValueError
            if command.get("op") == "load" and model is None:
                options = LoadRequest.model_validate(command)
                started = time.monotonic()
                path = Path(options.model_path)
                if not path.is_file():
                    reply(ok=False, error="LLM_MODEL_MISSING")
                    return
                if path.stat().st_size > MAX_MODEL_BYTES:
                    reply(ok=False, error="LLM_MODEL_TOO_LARGE")
                    return
                with path.open("rb") as source:
                    if source.read(4) != b"GGUF":
                        reply(ok=False, error="LLM_MODEL_INVALID")
                        return
                    source.seek(0)
                    checksum = hashlib.file_digest(source, "sha256").hexdigest()
                limit = options.memory_limit_mb * 1024**2
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
                try:
                    from llama_cpp import Llama
                except (ImportError, OSError):
                    reply(ok=False, error="LLM_DEPENDENCY_MISSING")
                    return
                try:
                    model = Llama(
                        model_path=str(path),
                        n_ctx=options.n_ctx,
                        n_threads=options.n_threads,
                        n_threads_batch=options.n_threads,
                        n_batch=64,
                        n_ubatch=64,
                        n_gpu_layers=0,
                        use_mmap=True,
                        use_mlock=False,
                        logits_all=False,
                        seed=42,
                        verbose=False,
                    )
                except MemoryError:
                    reply(ok=False, error="LLM_MEMORY_LIMIT")
                    return
                except Exception:
                    reply(ok=False, error="LLM_LOAD_FAILED")
                    return
                n_ctx = options.n_ctx
                reply(
                    ok=True,
                    result={
                        "sha256": checksum,
                        "model_bytes": path.stat().st_size,
                        "load_ms": float((time.monotonic() - started) * 1000),
                        "peak_rss_bytes": rss(),
                        "n_ctx": n_ctx,
                        "n_threads": options.n_threads,
                    },
                )
            elif command.get("op") == "generate" and model is not None:
                request = GenerateRequest.model_validate(command)
                started = time.monotonic()
                try:
                    result = model.create_chat_completion(
                        messages=[item.model_dump() for item in request.messages],
                        max_tokens=request.max_tokens,
                        temperature=0.0,
                        top_p=1.0,
                        response_format={"type": "json_object", "schema": request.schema_}
                        if request.schema_ is not None
                        else None,
                        stream=False,
                    )
                except ValueError:
                    reply(ok=False, error="LLM_CONTEXT_EXCEEDED")
                    continue
                except MemoryError:
                    reply(ok=False, error="LLM_MEMORY_LIMIT")
                    return
                except Exception:
                    reply(ok=False, error="LLM_INFERENCE_FAILED")
                    return
                choice = result["choices"][0]
                reply(
                    ok=True,
                    result={
                        "content": choice["message"]["content"],
                        "finish_reason": choice["finish_reason"],
                        "prompt_tokens": result["usage"]["prompt_tokens"],
                        "completion_tokens": result["usage"]["completion_tokens"],
                        "inference_ms": float((time.monotonic() - started) * 1000),
                        "peak_rss_bytes": rss(),
                    },
                )
                result, choice = None, None
            else:
                reply(ok=False, error="LLM_BAD_RESPONSE")
                return
        except MemoryError:
            reply(ok=False, error="LLM_MEMORY_LIMIT")
            return
        except (ValueError, ValidationError, KeyError, TypeError, OSError, RecursionError):
            reply(ok=False, error="LLM_BAD_RESPONSE")
            return
        finally:
            command, line = None, None
            request = None


if __name__ == "__main__":
    main()
