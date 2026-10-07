"""Wake-word barge-in while TTS is playing, using Windows STT text."""

from __future__ import annotations

import logging
import os
import threading
import time

from jarvis_pi.near_end import NearEndSpeechGate
from jarvis_pi.playback_timeline import PlaybackTimeline
from jarvis_pi.wake import find_wake_phrase

LOGGER = logging.getLogger("jarvis_pi.barge_in")

_NEAR_HOLD_SEC = 0.8


class BargeInDetector:
    """Confirm a wake phrase from remote STT while the speaker is active.

    The Pi does not run Vosk. Clean mic audio still goes to Windows; this
    object only decides whether that transcript is the user, not the speaker.
    """

    def __init__(
        self,
        *,
        wake_words: tuple[str, ...],
        timeline: PlaybackTimeline,
        on_trigger,
        gate: NearEndSpeechGate | None = None,
    ) -> None:
        self.wake_words = wake_words
        self.timeline = timeline
        self.on_trigger = on_trigger
        self.gate = gate or NearEndSpeechGate()
        self._enabled = threading.Event()
        self._fired = False
        self._near_until = 0.0
        self._disabled = os.getenv("BARGE_IN_ENABLED", "true").strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }
        if self._disabled:
            LOGGER.info("Barge-in disabled by BARGE_IN_ENABLED")

    def set_enabled(self, enabled: bool) -> None:
        if self._disabled:
            return
        if enabled:
            self._fired = False
            self._enabled.set()
        else:
            self._enabled.clear()

    def feed(self, clean_pcm: bytes, near_pcm: bytes, far_pcm: bytes) -> None:
        del clean_pcm
        if not self._enabled.is_set():
            return
        if self.gate.allows(near_pcm, far_pcm):
            self._near_until = time.monotonic() + _NEAR_HOLD_SEC

    def consider(self, text: str, *, is_final: bool) -> bool:
        """Return True when this STT text should interrupt TTS."""
        if not self._enabled.is_set() or self._fired or not is_final:
            return False
        wake_word, _remainder = find_wake_phrase(text, self.wake_words)
        if not wake_word:
            return False
        if self.timeline.covers_wake_word(wake_word):
            LOGGER.info("Ignoring wake that is part of the current TTS: %s", wake_word)
            return False
        if time.monotonic() > self._near_until:
            LOGGER.info("Ignoring wake without near-end speech energy: %s", wake_word)
            return False
        self._fired = True
        self._enabled.clear()
        LOGGER.info("Barge-in wake from Windows STT: %s", wake_word)
        self.on_trigger()
        return True
