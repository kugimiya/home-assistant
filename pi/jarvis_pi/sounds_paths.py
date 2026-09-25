"""Paths to bundled WAV feedback sounds."""

from __future__ import annotations

from pathlib import Path

SOUNDS_DIR = Path(__file__).resolve().parent / "sounds"


def accept_wav() -> Path:
    return SOUNDS_DIR / "accept.wav"


def decline_wav() -> Path:
    return SOUNDS_DIR / "decline.wav"


def timer_wav() -> Path:
    return SOUNDS_DIR / "timer.wav"


def networking_wav() -> Path:
    return SOUNDS_DIR / "networking.wav"
