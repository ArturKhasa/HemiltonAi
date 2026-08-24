"""Audio transcription via OpenAI Whisper."""
import logging

from openai import AsyncOpenAI

from app.config import settings
from app.ssl_trust import async_client

logger = logging.getLogger(__name__)

_AUDIO_EXTENSIONS = frozenset([".mp3", ".ogg", ".wav", ".m4a", ".aac", ".oga", ".opus", ".flac"])
# VK voice messages arrive as extensionless proxy URLs (.../vk/audio/get/<base64>).
_AUDIO_PATHS = ("/vk/audio/get/", "/audio/get/")


def is_audio_url(url: str) -> bool:
    lower = url.lower().split("?")[0]
    if any(path in lower for path in _AUDIO_PATHS):
        return True
    return any(lower.endswith(ext) for ext in _AUDIO_EXTENSIONS)


async def transcribe_audio_url(url: str) -> str | None:
    """Download audio from URL and transcribe via Whisper. Returns None on failure."""
    logger.info("transcribe_audio | url=%s", url)
    try:
        # Голосовое из MAX лежит на их хранилище с сертификатом Минцифры.
        async with async_client(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            audio_bytes = response.content
    except Exception as exc:
        logger.warning("transcribe_audio: download failed | url=%s | error=%s", url, exc)
        return None

    try:
        lower_url = url.lower().split("?")[0]
        ext = next((e for e in _AUDIO_EXTENSIONS if lower_url.endswith(e)), ".mp3")
        openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        transcript = await openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=(f"audio{ext}", audio_bytes),
            language="ru",
        )
        text = transcript.text.strip()
        logger.info("transcribe_audio done | url=%s | chars=%d", url, len(text))
        return text or None
    except Exception as exc:
        logger.warning("transcribe_audio: whisper failed | url=%s | error=%s", url, exc)
        return None
