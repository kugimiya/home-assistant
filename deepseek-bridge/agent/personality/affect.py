"""Heuristic tone of the latest user utterance. No model call."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Tone(str, Enum):
    NEUTRAL = "neutral"
    WARM = "warm"
    SHARP = "sharp"
    HOSTILE = "hostile"
    PROFANE = "profane"


_SWEAR = re.compile(
    r"\b("
    r"бля(?:ть|дь)?|хуй\w*|нахуй|похуй|пизд\w*|еба\w*|ёба\w*|сука|суки|мудак\w*|пидор\w*|гандон\w*"
    r")\b",
    re.IGNORECASE,
)
_WARM = re.compile(
    r"\b("
    r"спасибо|благодар\w*|пожалуйста|молодец|умница|люблю|добр\w*|мил\w*|"
    r"зайк\w*|солнышк\w*|хорош\w*|класно|классно|отлично"
    r")\b",
    re.IGNORECASE,
)
_HOSTILE = re.compile(
    r"\b("
    r"заткнись|завали|отвали|дур\w*|туп\w*|идиот\w*|дебил\w*|мраз\w*|"
    r"ненавиж\w*|бесишь|достал\w*|пошл\w+\s+нахуй"
    r")\b",
    re.IGNORECASE,
)
_SHARP = re.compile(
    r"\b(быстро|немедленно|чёрт|черт|блин|надоел\w*|хватит|молч\w*)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Affect:
    tone: Tone
    user_swears: bool


def classify(text: str) -> Affect:
    raw = text.strip()
    if not raw:
        return Affect(Tone.NEUTRAL, False)
    swears = bool(_SWEAR.search(raw))
    if swears or (bool(_HOSTILE.search(raw)) and swears):
        return Affect(Tone.PROFANE if swears else Tone.HOSTILE, swears)
    if _HOSTILE.search(raw):
        return Affect(Tone.HOSTILE, False)
    if _WARM.search(raw) and not _SHARP.search(raw):
        return Affect(Tone.WARM, False)
    if _SHARP.search(raw):
        return Affect(Tone.SHARP, False)
    return Affect(Tone.NEUTRAL, False)
