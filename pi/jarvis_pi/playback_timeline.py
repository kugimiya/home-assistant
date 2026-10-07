"""What TTS text is on the speaker right now (self-trigger filter)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from jarvis_pi.wake import normalize_text


@dataclass
class _Span:
    start: float
    end: float
    text: str


class PlaybackTimeline:
    def __init__(self) -> None:
        self._spans: list[_Span] = []

    def clear(self) -> None:
        self._spans.clear()

    def note(self, text: str, duration_sec: float, *, now: float | None = None) -> None:
        cleaned = normalize_text(text)
        if not cleaned or duration_sec <= 0:
            return
        start = time.monotonic() if now is None else now
        self._spans.append(_Span(start=start, end=start + duration_sec, text=cleaned))
        cutoff = start - 2.0
        self._spans = [span for span in self._spans if span.end >= cutoff]

    def covers_wake_word(self, wake_word: str, *, now: float | None = None) -> bool:
        word = normalize_text(wake_word)
        if not word:
            return False
        moment = time.monotonic() if now is None else now
        for span in self._spans:
            if span.start <= moment <= span.end and word in span.text:
                return True
        return False
