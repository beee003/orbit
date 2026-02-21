"""ElevenLabs TTS — text to speech for agent responses."""
import base64
import logging
import time
from typing import Optional

from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID

logger = logging.getLogger("orbit.tts")

_client = None


def _get_client():
    global _client
    if _client is None:
        from elevenlabs import ElevenLabs
        _client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        logger.info("Initialized ElevenLabs client")
    return _client


def synthesize(text: str, voice_id: Optional[str] = None) -> dict:
    """Convert text to speech, return base64-encoded MP3.

    Args:
        text: Text to speak (should be short — 1-2 sentences)
        voice_id: Override voice ID

    Returns:
        {audio_base64, text, latency_ms, size_bytes}
    """
    if not text or not text.strip():
        return {"audio_base64": "", "text": "", "latency_ms": 0, "size_bytes": 0}

    start = time.time()
    client = _get_client()
    vid = voice_id or ELEVENLABS_VOICE_ID

    audio_iterator = client.text_to_speech.convert(
        voice_id=vid,
        text=text,
        model_id="eleven_turbo_v2_5",
        output_format="mp3_44100_64",
        voice_settings={
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    )

    # Collect all chunks
    audio_bytes = b"".join(chunk for chunk in audio_iterator)
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    latency = (time.time() - start) * 1000

    logger.info(f"TTS: {len(text)} chars → {len(audio_bytes)} bytes in {latency:.0f}ms")
    return {
        "audio_base64": audio_b64,
        "text": text,
        "latency_ms": latency,
        "size_bytes": len(audio_bytes),
    }
