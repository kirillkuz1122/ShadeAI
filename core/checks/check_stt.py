"""Измерить уже подготовленный локальный STT по WAV, без HA и без сохранения речи."""

import argparse
import asyncio
import json
import platform
import sys
import time
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))


async def measure(audio, expected_action, expected_entity):
    from app.core.config import settings
    from app.services.voice.audio import read_pcm
    from app.services.voice.engine import STTEngine, available_memory
    from app.services.voice.intent import command

    read_pcm(audio)
    engine = STTEngine()
    before = available_memory()
    started = time.monotonic()
    try:
        result = await engine.transcribe(audio)
        entity, action, _ = command(result.text, settings.voice_targets)
        match = (expected_action is None or action == expected_action) and (
            expected_entity is None or entity == expected_entity
        )
        return dict(
            native_stt=True,
            ha_commands=0,
            hardware_acceptance=False,
            machine=platform.machine(),
            audio_bytes=len(audio),
            latency_ms=round((time.monotonic() - started) * 1000, 2),
            child_peak_rss_kib=result.peak_rss_kib,
            available_ram_before=before,
            process_virtual_memory_mb=settings.voice_memory_limit_mb,
            model_manifest_sha256=settings.voice_model_manifest_sha256,
            action=action,
            entity_id=entity,
            expectation_supplied=expected_action is not None or expected_entity is not None,
            expected_intent_matches=match
            if expected_action is not None or expected_entity is not None
            else None,
            transcript_saved=False,
        )
    finally:
        await engine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-action", choices=["turn_on", "turn_off"])
    parser.add_argument("--expect-entity")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Существующий отчёт не перезаписывается")
    if not 44 <= args.wav.stat().st_size <= 320044:
        parser.error("Нужен PCM WAV≤10сек/320044байт")
    from app.services.voice.errors import VoiceError

    try:
        result = asyncio.run(measure(args.wav.read_bytes(), args.expect_action, args.expect_entity))
    except VoiceError as error:
        raise SystemExit(error.code) from None
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["expected_intent_matches"] is not False else 1)


if __name__ == "__main__":
    main()
