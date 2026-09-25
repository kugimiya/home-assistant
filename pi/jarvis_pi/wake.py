"""Wake-word state machine driven by remote STT text."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

LOGGER = logging.getLogger("jarvis_pi.wake")


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


@dataclass
class WakeStateMachine:
    wake_words: tuple[str, ...]
    command_window_sec: float

    def __post_init__(self) -> None:
        self._wake_words = tuple(
            sorted(
                (normalize_text(word) for word in self.wake_words if word),
                key=len,
                reverse=True,
            )
        )
        self._awake = False
        self._awake_since = 0.0

    def reset(self) -> None:
        self._awake = False
        self._awake_since = 0.0

    def _find_wake(self, normalized: str) -> tuple[str | None, str]:
        matched = [word for word in self._wake_words if word in normalized]
        if not matched:
            return None, ""
        wake_word = max(matched, key=len)
        index = normalized.find(wake_word)
        remainder = normalized[index + len(wake_word) :].strip()
        return wake_word, remainder

    def _is_timed_out(self) -> bool:
        return time.time() - self._awake_since > self.command_window_sec

    def _partial_extends_waiting(self, normalized: str) -> bool:
        """True when partial looks like the user is still forming a command."""
        wake_word, remainder = self._find_wake(normalized)
        if wake_word and not remainder:
            return False
        return bool(normalized)

    def process(self, text: str, is_final: bool) -> tuple[str | None, bool, bool]:
        """Return command text, woke_now, timed_out."""
        normalized = normalize_text(text)
        if not normalized:
            return None, False, False

        if not self._awake:
            wake_word, remainder = self._find_wake(normalized)
            if not wake_word:
                return None, False, False

            if not is_final:
                if remainder:
                    return None, False, False
                self._awake = True
                self._awake_since = time.time()
                return None, True, False

            self._awake = True
            self._awake_since = time.time()
            if remainder:
                self._awake = False
                return remainder, True, False
            return None, True, False

        if not is_final:
            if self._partial_extends_waiting(normalized):
                self._awake_since = time.time()
                LOGGER.info("Command window extended (partial): %s", normalized)
            if self._is_timed_out():
                self._awake = False
                return None, False, True
            return None, False, False

        if self._is_timed_out():
            self._awake = False
            return None, False, True

        wake_word, remainder = self._find_wake(normalized)
        if wake_word and not remainder:
            return None, False, False

        self._awake = False
        if remainder:
            return remainder, False, False
        return normalized, False, False

    def check_timeout(self) -> bool:
        if self._awake and self._is_timed_out():
            self._awake = False
            return True
        return False
