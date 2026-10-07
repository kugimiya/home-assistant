"""Linear PCM resampling for the 16 kHz duplex pipeline."""

from __future__ import annotations

import numpy as np


def resample_s16_mono(pcm: bytes, source_rate: int, target_rate: int = 16000) -> bytes:
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("sample rates must be positive")
    if len(pcm) < 2:
        return b""
    if len(pcm) % 2:
        pcm = pcm[:-1]
    if source_rate == target_rate:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return b""
    duration = samples.size / float(source_rate)
    target_count = max(1, int(round(duration * target_rate)))
    source_pos = np.linspace(0.0, samples.size - 1, num=samples.size)
    target_pos = np.linspace(0.0, samples.size - 1, num=target_count)
    converted = np.interp(target_pos, source_pos, samples)
    return converted.clip(-32768, 32767).astype(np.int16).tobytes()
