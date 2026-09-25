"""Vosk streaming recognizer."""

from __future__ import annotations

import json
import os

from vosk import EndpointerMode, KaldiRecognizer, Model, SetLogLevel


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _parse_endpointer_mode(raw: str) -> EndpointerMode:
    value = raw.strip().lower()
    if value in {"very_long", "very-long", "verylong"}:
        return EndpointerMode.VERY_LONG
    if value in {"long", "default", ""}:
        return EndpointerMode.LONG if value == "long" else EndpointerMode.DEFAULT
    if value == "short":
        return EndpointerMode.SHORT
    return EndpointerMode.LONG


def _configure_recognizer(recognizer: KaldiRecognizer) -> None:
    mode = _parse_endpointer_mode(os.getenv("VOSK_ENDPOINT_MODE", "long"))
    recognizer.SetEndpointerMode(mode)

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
