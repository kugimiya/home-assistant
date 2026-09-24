"""Vosk streaming recognizer."""

from __future__ import annotations

import json

from vosk import KaldiRecognizer, Model, SetLogLevel


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


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
