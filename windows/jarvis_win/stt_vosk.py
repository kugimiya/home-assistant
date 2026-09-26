"""Vosk streaming recognizer."""

from __future__ import annotations

import json
import logging
import os

from vosk import KaldiRecognizer, Model, SetLogLevel

LOGGER = logging.getLogger("jarvis_win.stt_vosk")

# vosk.EndpointerMode values (stable in vosk-api)
_ENDPOINT_DEFAULT = 0
_ENDPOINT_SHORT = 1
_ENDPOINT_LONG = 2
_ENDPOINT_VERY_LONG = 3


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _endpointer_mode_value(raw: str) -> int:
    value = raw.strip().lower()
    if value in {"very_long", "very-long", "verylong"}:
        return _ENDPOINT_VERY_LONG
    if value == "long":
        return _ENDPOINT_LONG
    if value == "short":
        return _ENDPOINT_SHORT
    if value in {"default", ""}:
        return _ENDPOINT_DEFAULT
    return _ENDPOINT_LONG


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
        mode = _endpointer_mode_value(os.getenv("VOSK_ENDPOINT_MODE", "long"))
        recognizer.SetEndpointerMode(mode)

    if has_delays:
        t_start_max = float(os.getenv("VOSK_ENDPOINT_START_MAX_SEC", "5.0"))
        t_end = float(os.getenv("VOSK_ENDPOINT_TRAILING_SEC", "1.2"))
        t_max = float(os.getenv("VOSK_ENDPOINT_MAX_UTTERANCE_SEC", "30.0"))
        recognizer.SetEndpointerDelays(t_start_max, t_end, t_max)


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
