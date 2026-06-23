"""Wake word + voice loop (mic -> wake -> STT -> core -> TTS -> speaker).

"Hey IRIS" is detected by Porcupine; on wake we capture an utterance, transcribe
it (STT), send the TEXT to the core via ``POST /chat`` (ONLY text crosses into
the core — never raw audio), then speak the reply (TTS). Mirrors the FRIDAY
reference pipeline; LiveKit can replace the local mic/speaker transport for
remote/streaming use (see README) without changing this flow.

All audio libs are lazy-imported so importing this module stays cheap.
"""

from __future__ import annotations

import asyncio

import structlog

from iris.config.settings import get_settings
from iris.voice.stt import STT, get_stt
from iris.voice.tts import TTS, get_tts

log = structlog.get_logger(__name__)

_FRAME_RATE = 16000          # Porcupine + capture sample rate
_UTTERANCE_SECONDS = 5       # how long to record after wake


class WakeWord:
    """Porcupine "Hey IRIS" detector. ``wait()`` blocks until the word is heard."""

    def __init__(self) -> None:
        settings = get_settings()
        self._access_key = settings.PORCUPINE_ACCESS_KEY
        self._keyword_path = settings.PORCUPINE_KEYWORD_PATH
        self._porcupine = None
        self._stream = None

    def _ensure(self):
        if self._porcupine is not None:
            return
        import pvporcupine  # lazy
        import sounddevice as sd  # lazy

        if not self._access_key:
            raise RuntimeError("PORCUPINE_ACCESS_KEY not set (configure in .env).")
        kwargs = {"access_key": self._access_key}
        if self._keyword_path:
            kwargs["keyword_paths"] = [self._keyword_path]
        else:
            kwargs["keywords"] = ["hey google"]  # placeholder until custom .ppn added
        self._porcupine = pvporcupine.create(**kwargs)
        self._stream = sd.RawInputStream(
            samplerate=self._porcupine.sample_rate,
            blocksize=self._porcupine.frame_length,
            dtype="int16",
            channels=1,
        )
        self._stream.start()

    async def wait(self) -> None:
        self._ensure()
        await asyncio.to_thread(self._wait_sync)

    def _wait_sync(self) -> None:
        import struct

        while True:
            pcm, _ = self._stream.read(self._porcupine.frame_length)
            frame = struct.unpack_from("h" * self._porcupine.frame_length, pcm)
            if self._porcupine.process(frame) >= 0:
                return

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        if self._porcupine is not None:
            self._porcupine.delete()


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
