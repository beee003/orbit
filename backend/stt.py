"""Speech-to-text using ElevenLabs Scribe — best-in-class accuracy (~3.5% WER)."""
import io
import logging
import time

import httpx
from config import ELEVENLABS_API_KEY

logger = logging.getLogger("orbit.stt")

SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"


def transcribe(audio_bytes: bytes, mime_type: str = "audio/webm") -> dict:
    """Transcribe audio using ElevenLabs Scribe.

    Args:
        audio_bytes: Raw audio data
        mime_type: Audio MIME type (audio/webm, audio/wav, etc.)

    Returns:
        {text, latency_ms, language}
    """
    start = time.time()

    # Map mime type to file extension
    ext_map = {"audio/webm": "webm", "audio/wav": "wav", "audio/mp3": "mp3", "audio/ogg": "ogg"}
    ext = ext_map.get(mime_type, "webm")

    resp = httpx.post(
        SCRIBE_URL,
        headers={"xi-api-key": ELEVENLABS_API_KEY},
        files={"file": (f"audio.{ext}", audio_bytes, mime_type)},
        data={"model_id": "scribe_v1"},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()

    text = data.get("text", "").strip()
    language = data.get("language_code", "en")
    latency = (time.time() - start) * 1000

    logger.info(f"STT: {len(audio_bytes)} bytes → '{text[:80]}' in {latency:.0f}ms (lang={language})")
    return {"text": text, "latency_ms": latency, "language": language}
