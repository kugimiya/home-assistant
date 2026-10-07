"""Wake-word state machine driven by remote STT text."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

LOGGER = logging.getLogger("jarvis_pi.wake")


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _sorted_wake_words(wake_words: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            (normalize_text(word) for word in wake_words if word),
            key=len,
            reverse=True,
        )
    )


def find_wake_phrase(text: str, wake_words: tuple[str, ...]) -> tuple[str | None, str]:
    """Return matched wake word and remainder after it (both normalized)."""
    normalized = normalize_text(text)
    if not normalized:
        return None, ""
    for word in _sorted_wake_words(wake_words):
        index = normalized.find(word)
        if index != -1:
            remainder = normalized[index + len(word) :].strip()
            return word, remainder
    return None, ""


def text_contains_wake_word(text: str, wake_words: tuple[str, ...]) -> bool:
    wake_word, _ = find_wake_phrase(text, wake_words)
    return wake_word is not None


@dataclass
class WakeStateMachine:
    wake_words: tuple[str, ...]
    command_window_sec: float

    def __post_init__(self) -> None:
        self._wake_words = _sorted_wake_words(self.wake_words)
        self._awake = False
        self._awake_since = 0.0

    def reset(self) -> None:
        self._awake = False
        self._awake_since = 0.0

    def arm_listening(self) -> None:
        """Open the command window without a wake phrase (follow-up turn)."""
        self._awake = True
        self._awake_since = time.time()

    def _find_wake(self, normalized: str) -> tuple[str | None, str]:
        wake_word, remainder = find_wake_phrase(normalized, self.wake_words)
        if wake_word is None:
            return None, ""
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
            # Wake-only final while already listening: keep window open.
            self._awake_since = time.time()
            return None, False, False

        # Keep listening until the caller commits/processes the command.
        # Clearing awake here dropped follow-up finals during STT_COMMAND_COMMIT_SEC.
        self._awake_since = time.time()
        if remainder:
            return remainder, False, False
        return normalized, False, False

    def check_timeout(self) -> bool:
        if self._awake and self._is_timed_out():
            self._awake = False
            return True
        return False
