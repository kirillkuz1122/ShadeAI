import re
import unicodedata

from app.services.voice.errors import VoiceError


def normalize(text: str) -> str:
    if not isinstance(text, str) or not 1 <= len(text) <= 512 or any(ord(c) < 32 for c in text):
        raise VoiceError("VOICE_UNSUPPORTED")
    return " ".join(
        unicodedata.normalize("NFKC", text).lower().replace("ё", "е").strip(" .!?").split()
    )


def command(text: str, aliases: dict[str, str]) -> tuple[str, str, str]:
    normalized = normalize(text)
    matched = re.fullmatch(r"(включи|включить|выключи|выключить) (.+)", normalized)
    if matched is None or matched[2] not in aliases:
        raise VoiceError("VOICE_UNSUPPORTED")
    return (
        aliases[matched[2]],
        "turn_on" if matched[1] in {"включи", "включить"} else "turn_off",
        matched[2],
    )
