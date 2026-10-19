import hashlib
import io
import wave

from app.services.voice.errors import VoiceError

MAX_AUDIO_BYTES = 320_044


def read_pcm(data: bytes) -> bytes:
    try:
        if not 44 <= len(data) <= MAX_AUDIO_BYTES or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise ValueError
        if int.from_bytes(data[4:8], "little") != len(data) - 8:
            raise ValueError
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (
                audio.getnchannels(),
                audio.getsampwidth(),
                audio.getframerate(),
                audio.getcomptype(),
            ) != (1, 2, 16000, "NONE"):
                raise ValueError
            if not 4000 <= audio.getnframes() <= 160000:
                raise ValueError
            pcm = audio.readframes(160001)
            if len(pcm) != audio.getnframes() * 2:
                raise ValueError
        return pcm
    except (ValueError, wave.Error, EOFError):
        raise VoiceError("VOICE_BAD_AUDIO") from None


def payload_digest(source: str, data: bytes) -> str:
    return hashlib.sha256(source.encode() + b"\0" + data).hexdigest()
