"""Text-to-speech adapters (GOLDEN RULE #10: swap provider in one file).

Default: Kokoro-82M, female voice "af_heart" (local, offline). Fallback: Gemini
TTS (female prebuilt voice). Both implement the same ``TTS`` interface and return
a :class:`SpeechResult` (WAV audio + word timestamps). Heavy deps are
lazy-imported so ``from iris.voice.tts import TTS`` stays cheap.

The Gemini TTS model id comes from the router (GOLDEN RULE #2), never hardcoded
here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import structlog

from iris.config.settings import get_settings
from iris.voice._audio import float_to_pcm16, pcm16_to_wav_bytes

log = structlog.get_logger(__name__)


@dataclass
class SpeechResult:
    """Synthesised speech: WAV audio bytes + optional word timestamps."""

    audio: bytes                       # WAV-format bytes
    sample_rate: int = 24000
    word_timestamps: list[dict] = field(default_factory=list)


class TTS(ABC):
    """Abstract text-to-speech engine."""

    @abstractmethod
    async def speak(self, text: str) -> SpeechResult:
        """Synthesise ``text`` to speech (WAV + word timestamps)."""
        raise NotImplementedError


class KokoroTTS(TTS):
    """Kokoro-82M (ONNX), female voice 'af_heart'. Local + offline.

    Requires ``kokoro-onnx`` plus the model + voices files (see README). If those
    aren't present, construction raises and ``get_tts`` falls back to Gemini.
    """

    def __init__(self, voice: str | None = None) -> None:
        settings = get_settings()
        self._voice = voice or settings.TTS_VOICE
        self._rate = settings.TTS_SAMPLE_RATE
        self._kokoro = self._load(settings)

    @staticmethod
    def _load(settings):
        from kokoro_onnx import Kokoro  # lazy; raises if not installed

        model = settings.KOKORO_MODEL_PATH or "kokoro-v1.0.onnx"
        voices = settings.KOKORO_VOICES_PATH or "voices-v1.0.bin"
        return Kokoro(model, voices)

    async def speak(self, text: str) -> SpeechResult:
        import asyncio

        return await asyncio.to_thread(self._speak_sync, text)

    def _speak_sync(self, text: str) -> SpeechResult:
        samples, rate = self._kokoro.create(text, voice=self._voice, speed=1.0, lang="en-us")
        pcm = float_to_pcm16(samples)
        return SpeechResult(audio=pcm16_to_wav_bytes(pcm, rate), sample_rate=rate)


class GeminiTTS(TTS):
    """Gemini TTS fallback — female prebuilt voice. Uses the API key from settings."""

    def __init__(self, voice: str | None = None) -> None:
        settings = get_settings()
        self._voice = voice or settings.GEMINI_TTS_VOICE
        self._api_key = settings.GEMINI_API_KEY

    async def speak(self, text: str) -> SpeechResult:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY not set (configure in .env via settings).")
        from google import genai
        from google.genai import types

        from iris.router.model_router import tts_model

        client = genai.Client(api_key=self._api_key)
        resp = await client.aio.models.generate_content(
            model=tts_model(),
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice)
                    )
                ),
            ),
        )
        pcm, rate = _extract_pcm(resp)
        return SpeechResult(audio=pcm16_to_wav_bytes(pcm, rate), sample_rate=rate)


def get_tts() -> TTS:
    """Return the configured TTS engine; fall back to Gemini if Kokoro is absent.

    The ONE place the provider is chosen.
    """
    settings = get_settings()
    if settings.TTS_PROVIDER == "gemini":
        return GeminiTTS()
    try:
        return KokoroTTS()
    except Exception as exc:  # noqa: BLE001 — Kokoro model/files missing -> fallback
        log.info("tts.fallback_gemini", reason=str(exc))
        return GeminiTTS()


def _extract_pcm(resp) -> tuple[bytes, int]:
    """Pull PCM bytes + sample rate from a Gemini audio response."""
    for cand in getattr(resp, "candidates", None) or []:
        for part in getattr(getattr(cand, "content", None), "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                rate = _rate_from_mime(getattr(inline, "mime_type", "") or "")
                return inline.data, rate
    raise RuntimeError("Gemini TTS returned no audio.")


def _rate_from_mime(mime: str, default: int = 24000) -> int:
    # e.g. "audio/L16;rate=24000"
    for part in mime.split(";"):
        part = part.strip()
        if part.startswith("rate="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return default
    return default
