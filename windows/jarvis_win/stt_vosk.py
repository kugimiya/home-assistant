"""Vosk streaming recognizer."""

from __future__ import annotations

import json
import logging
import os

from vosk import KaldiRecognizer, Model, SetLogLevel

LOGGER = logging.getLogger("jarvis_win.stt_vosk")

try:
    from vosk import EndpointerMode as _EndpointerMode
except ImportError:  # older vosk wheels without the enum
    _EndpointerMode = None  # type: ignore[misc, assignment]


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _endpointer_mode(raw: str):
    """Return vosk EndpointerMode enum (0.3.50+) or int fallback."""
    value = raw.strip().lower()
    if _EndpointerMode is not None:
        if value in {"very_long", "very-long", "verylong"}:
            return _EndpointerMode.VERY_LONG
        if value == "long":
            return _EndpointerMode.LONG
        if value == "short":
            return _EndpointerMode.SHORT
        if value in {"default", ""}:
            return _EndpointerMode.DEFAULT
        return _EndpointerMode.LONG

    if value in {"very_long", "very-long", "verylong"}:
        return 3
    if value == "long":
        return 2
    if value == "short":
        return 1
    if value in {"default", ""}:
        return 0
    return 2


def _configure_recognizer(recognizer: KaldiRecognizer) -> None:
    has_mode = hasattr(recognizer, "SetEndpointerMode")
    has_delays = hasattr(recognizer, "SetEndpointerDelays")
    if not has_mode and not has_delays:
        LOGGER.warning(
            "Installed vosk has no SetEndpointerMode/SetEndpointerDelays; "
            "early STT finals may still happen. Use Pi STT_COMMAND_COMMIT_SEC."
        )
        return

    if has_mode:
        mode = _endpointer_mode(os.getenv("VOSK_ENDPOINT_MODE", "long"))
        try:
            recognizer.SetEndpointerMode(mode)
        except Exception:
            LOGGER.exception("SetEndpointerMode(%s) failed", mode)

    if has_delays:
        t_start_max = float(os.getenv("VOSK_ENDPOINT_START_MAX_SEC", "5.0"))
        t_end = float(os.getenv("VOSK_ENDPOINT_TRAILING_SEC", "1.2"))
        t_max = float(os.getenv("VOSK_ENDPOINT_MAX_UTTERANCE_SEC", "30.0"))
        try:
            recognizer.SetEndpointerDelays(t_start_max, t_end, t_max)
        except Exception:
            LOGGER.exception(
                "SetEndpointerDelays(%s, %s, %s) failed",
                t_start_max,
                t_end,
                t_max,
            )


class VoskEngine:
    """Loads the Vosk model once and creates per-session recognizers."""

    def __init__(self, model_path: str, sample_rate: int) -> None:
        SetLogLevel(-1)
        self._model = Model(model_path)
        self._sample_rate = sample_rate

    def create_recognizer(self) -> StreamingRecognizer:
        return StreamingRecognizer(self._model, self._sample_rate)


class StreamingRecognizer:
    def __init__(self, model: Model, sample_rate: int) -> None:
        self._recognizer = KaldiRecognizer(model, sample_rate)
        _configure_recognizer(self._recognizer)

    def feed(self, chunk: bytes) -> list[tuple[str, bool]]:
        events: list[tuple[str, bool]] = []
        if self._recognizer.AcceptWaveform(chunk):
            result = json.loads(self._recognizer.Result())
            text = normalize_text(result.get("text", ""))
            if text:
                events.append((text, True))
        else:
            partial = json.loads(self._recognizer.PartialResult())
            text = normalize_text(partial.get("partial", ""))
            if text:
                events.append((text, False))
        return events
