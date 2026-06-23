"""Audio helpers — PCM16 <-> WAV, used by the voice adapters (stdlib only)."""

from __future__ import annotations

import io
import wave


def pcm16_to_wav_bytes(pcm: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    """Wrap raw 16-bit little-endian PCM samples in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def float_to_pcm16(samples) -> bytes:
    """Convert float32 samples in [-1, 1] to PCM16 bytes."""
    import numpy as np

    arr = np.asarray(samples, dtype="float32")
    clipped = np.clip(arr, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()
