"""Wake word + voice loop (mic -> wake -> STT -> core -> TTS -> speaker).

"Hey IRIS" is detected by **openWakeWord** (Apache-2.0, fully local, no API key,
no trial); on wake we capture an utterance, transcribe it (STT), send the TEXT
to the core via ``POST /chat`` (ONLY text crosses into the core — never raw
audio), then speak the reply (TTS). Mirrors the FRIDAY reference pipeline;
LiveKit can replace the local mic/speaker transport for remote/streaming use
(see README) without changing this flow.

All audio libs are lazy-imported so importing this module stays cheap.
"""

from __future__ import annotations

import asyncio

import structlog

from iris.config.settings import get_settings
from iris.voice.stt import STT, get_stt
from iris.voice.tts import TTS, get_tts

log = structlog.get_logger(__name__)

_FRAME_RATE = 16000          # capture sample rate (openWakeWord + whisper)
_OWW_CHUNK = 1280            # openWakeWord frame: 80 ms @ 16 kHz
_UTTERANCE_SECONDS = 5       # how long to record after wake


class WakeWord:
    """openWakeWord "Hey IRIS" detector. ``wait()`` blocks until the word fires.

    Default uses a pretrained model (``WAKE_MODEL``); point ``WAKE_MODEL_PATH`` at
    a custom-trained "Hey IRIS" .onnx for the real wake phrase (see README).
    No access key, no trial — fully open-source and local.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._model_ref = settings.WAKE_MODEL_PATH or settings.WAKE_MODEL
        self._threshold = settings.WAKE_THRESHOLD
        self._model = None
        self._stream = None

    def _ensure(self):
        if self._model is not None:
            return
        import sounddevice as sd  # lazy
        from openwakeword.model import Model  # lazy

        # Ensure pretrained models are present (no-op if a custom path is used).
        try:
            import openwakeword

            openwakeword.utils.download_models()
        except Exception:  # noqa: BLE001 — custom model path doesn't need this
            pass

        self._model = Model(wakeword_models=[self._model_ref])
        self._stream = sd.RawInputStream(
            samplerate=_FRAME_RATE, blocksize=_OWW_CHUNK, dtype="int16", channels=1
        )
        self._stream.start()

    async def wait(self) -> None:
        self._ensure()
        await asyncio.to_thread(self._wait_sync)

    def _wait_sync(self) -> None:
        import numpy as np

        self._model.reset()
        while True:
            pcm, _ = self._stream.read(_OWW_CHUNK)
            frame = np.frombuffer(bytes(pcm), dtype=np.int16)
            scores = self._model.predict(frame)
            if any(score >= self._threshold for score in scores.values()):
                return

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()


class VoiceLoop:
    """Full local voice loop. Inject STT/TTS or let it pick the configured ones."""

    def __init__(self, stt: STT | None = None, tts: TTS | None = None) -> None:
        self._stt = stt or get_stt()
        self._tts = tts or get_tts()
        self._chat_url = get_settings().VOICE_CHAT_URL

    async def run_forever(self) -> None:
        wake = WakeWord()
        try:
            while True:
                await wake.wait()
                log.info("voice.wake")
                await self.handle_utterance()
        finally:
            wake.close()

    async def handle_utterance(self) -> str:
        audio = await self._record(_UTTERANCE_SECONDS)
        text = await self._stt.transcribe(audio, sample_rate=_FRAME_RATE)
        if not text:
            return ""
        log.info("voice.transcript", text=text)
        reply = await self._send_to_core(text)   # ONLY text crosses into the core
        await self.say(reply)
        return reply

    async def say(self, text: str) -> None:
        result = await self._tts.speak(text)
        await self._play(result.audio)

    # ── transport (local mic/speaker; swap for LiveKit) ──────────────────────
    async def _record(self, seconds: int) -> bytes:
        def _rec() -> bytes:
            import sounddevice as sd

            frames = sd.rec(int(seconds * _FRAME_RATE), samplerate=_FRAME_RATE,
                            channels=1, dtype="int16")
            sd.wait()
            return frames.tobytes()

        return await asyncio.to_thread(_rec)

    async def _play(self, wav_bytes: bytes) -> None:
        def _pl() -> None:
            import io
            import wave

            import sounddevice as sd

            with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
                rate = wav.getframerate()
                data = wav.readframes(wav.getnframes())
            import numpy as np

            sd.play(np.frombuffer(data, dtype="int16"), rate)
            sd.wait()

        await asyncio.to_thread(_pl)

    async def _send_to_core(self, text: str) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(self._chat_url, json={"message": text})
            resp.raise_for_status()
            return resp.json().get("reply", "")


async def _main() -> None:
    await VoiceLoop().run_forever()


if __name__ == "__main__":
    asyncio.run(_main())
