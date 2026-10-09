"""Reject wake hits that are only speaker echo (near-end energy gate)."""

from __future__ import annotations

import os

import numpy as np


def pcm_rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    if len(pcm) % 2:
        pcm = pcm[:-1]
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples * samples)))


class NearEndSpeechGate:
    def __init__(self, threshold: float | None = None, ratio: float | None = None) -> None:
        if threshold is None:
            threshold = float(os.getenv("NEAR_END_RMS_THRESHOLD", "400"))
        if ratio is None:
            ratio = float(os.getenv("NEAR_END_FAR_RATIO", "1.15"))
        self.threshold = threshold
        self.ratio = ratio

    def allows(self, near_pcm: bytes, far_pcm: bytes) -> bool:
        near = pcm_rms(near_pcm)
        far = pcm_rms(far_pcm)
        del far
        return near >= self.threshold
