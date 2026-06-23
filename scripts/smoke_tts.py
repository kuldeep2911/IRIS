"""Smoke test: synthesise IRIS saying 'IRIS online' in the female voice -> WAV.

Uses the configured TTS engine (Kokoro 'af_heart' if installed, else the Gemini
female-voice fallback). Writes workspace/iris_online.wav and asserts it's a
non-empty WAV.

Run: ``python scripts/smoke_tts.py``
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from iris.voice.tts import get_tts  # noqa: E402

OUT = ROOT / "workspace" / "iris_online.wav"


async def main() -> None:
    tts = get_tts()
    print("engine:", type(tts).__name__)
    result = await tts.speak("IRIS online")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(result.audio)

    size = OUT.stat().st_size
    print(f"wrote {OUT.name}: {size} bytes @ {result.sample_rate} Hz")
    assert result.audio[:4] == b"RIFF", "not a WAV file"
    assert size > 1000, "audio suspiciously small"
    print("TTS smoke: OK (female-voice WAV written)")


if __name__ == "__main__":
    asyncio.run(main())
