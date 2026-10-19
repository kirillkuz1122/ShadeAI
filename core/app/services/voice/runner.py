"""Одноразовый STT child: только локальный model_path и bounded stdio."""

import json
import os
import resource
import socket
import sys
from pathlib import Path


def main():
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    with open(os.devnull, "wb") as silent:
        os.dup2(silent.fileno(), 1)
        os.dup2(silent.fileno(), 2)
    try:
        header = sys.stdin.buffer.readline(4097)
        if len(header) > 4096:
            raise ValueError
        request = json.loads(header)
        memory = int(request["memory_mb"])
        timeout = int(request["timeout_seconds"])
        size = int(request["audio_size"])
        if not 256 <= memory <= 1024 or not 5 <= timeout <= 45 or not 44 <= size <= 320044:
            raise ValueError
        resource.setrlimit(resource.RLIMIT_AS, (memory * 1024**2,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (timeout + 2,) * 2)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        audio = sys.stdin.buffer.read(size + 1)
        if len(audio) != size:
            raise ValueError
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from app.services.voice.audio import read_pcm
        from app.services.voice.model_manifest import validate

        pcm = read_pcm(audio)
        validate(Path(request["model_path"]), request["manifest_sha256"])

        def denied(*args, **kwargs):
            raise OSError("STT_NETWORK_DISABLED")

        class OfflineSocket(socket.socket):
            connect = denied
            connect_ex = denied
            sendto = denied

        socket.socket = OfflineSocket
        socket.getaddrinfo = denied
        socket.create_connection = denied
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError:
            protocol.write(b'{"error":"STT_DEPENDENCY_MISSING"}\n')
            return
        SetLogLevel(-1)
        model = Model(str(Path(request["model_path"]).resolve()))
        recognizer = KaldiRecognizer(model, 16000)
        recognizer.SetWords(True)
        parts, words = [], []
        for index in range(0, len(pcm), 8000):
            if recognizer.AcceptWaveform(pcm[index : index + 8000]):
                result = json.loads(recognizer.Result())
                parts.append(result.get("text", ""))
                words.extend(result.get("result", []))
        final = json.loads(recognizer.FinalResult())
        parts.append(final.get("text", ""))
        words.extend(final.get("result", []))
        text = " ".join(p for p in parts if p)
        if len(text) > 512 or len(words) > 128:
            raise ValueError
        confidence = min((w["conf"] for w in words), default=0.0)
        packet = json.dumps(
            dict(
                text=text,
                confidence=confidence,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            ),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        if len(packet) > 8192:
            raise ValueError
        protocol.write(packet + b"\n")
    except Exception:
        protocol.write(b'{"error":"STT_FAILED"}\n')


if __name__ == "__main__":
    main()
