"""Speech-to-text adapters (GOLDEN RULE #10: swap provider in one file).

Default: Sarvam v3 (Indian English), matching the FRIDAY reference. Fallback:
local faster-whisper. Both implement the same ``STT`` interface, so the rest of
the system never knows which engine is running. Heavy deps are lazy-imported so
``from iris.voice.stt import STT`` stays cheap.

Interface: ``async transcribe(audio, sample_rate=16000, language=None) -> str``.
``audio`` is raw PCM16 mono bytes (or WAV bytes for Sarvam).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

from iris.config.settings import get_settings

log = structlog.get_logger(__name__)


class STT(ABC):
    """Abstract speech-to-text engine."""

    @abstractmethod
    async def transcribe(
        self, audio: bytes, sample_rate: int = 16000, language: str | None = None
    ) -> str:
        """Transcribe PCM16/WAV audio to text."""
        raise NotImplementedError


class SarvamSTT(STT):
    """Sarvam AI STT — default, tuned for Indian English. API key via settings."""

    API_URL = "https://api.sarvam.ai/speech-to-text"

    def __init__(self, api_key: str | None = None, language: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.SARVAM_API_KEY
        # Sarvam uses BCP-47 codes (Indian English); independent of whisper's hint.
        self._language = language or "en-IN"

    async def transcribe(
        self, audio: bytes, sample_rate: int = 16000, language: str | None = None
    ) -> str:
        if not self._api_key:
            raise RuntimeError("SARVAM_API_KEY not set (configure in .env via settings).")
        import httpx

        from iris.voice._audio import pcm16_to_wav_bytes

        wav = audio if _looks_like_wav(audio) else pcm16_to_wav_bytes(audio, sample_rate)
        files = {"file": ("audio.wav", wav, "audio/wav")}
        data = {"model": "saarika:v2", "language_code": language or self._language}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.API_URL, headers={"api-subscription-key": self._api_key},
                files=files, data=data,
            )
            resp.raise_for_status()
            return (resp.json().get("transcript") or "").strip()


class WhisperSTT(STT):
    """Local faster-whisper fallback — no API key, runs offline."""

    def __init__(self, model_size: str | None = None) -> None:
        self._model_size = model_size or get_settings().WHISPER_MODEL
        self._model = None  # lazily loaded

    async def transcribe(
        self, audio: bytes, sample_rate: int = 16000, language: str | None = None
    ) -> str:
        import asyncio

        return await asyncio.to_thread(self._transcribe_sync, audio, sample_rate, language)

    def _transcribe_sync(self, audio: bytes, sample_rate: int, language: str | None) -> str:
        import numpy as np
        from faster_whisper import WhisperModel

        if self._model is None:
            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(samples, language=(language or "en")[:2])
        return " ".join(seg.text for seg in segments).strip()


def get_stt() -> STT:
    """Return the configured STT engine (the ONE place the provider is chosen).

    Default is faster-whisper (free, local, no key). Sarvam is used only when
    explicitly selected AND a key is present.
    """
    settings = get_settings()
    if settings.STT_PROVIDER == "sarvam":
        if settings.SARVAM_API_KEY:
            return SarvamSTT()
        log.info("stt.fallback_whisper", reason="STT_PROVIDER=sarvam but no SARVAM_API_KEY")
    return WhisperSTT()


def _looks_like_wav(audio: bytes) -> bool:
    return len(audio) >= 4 and audio[:4] == b"RIFF"
