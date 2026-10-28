"""Effective axes: slow trust lerp plus this-turn mirror."""

from __future__ import annotations

from dataclasses import dataclass

from agent.personality.affect import Affect, Tone
from agent.personality.overlay import SelfOverlay, load_overlay
from agent.personality.state import (
    FACTORY_IRONY,
    FACTORY_SHARPNESS,
    FACTORY_WARMTH,
    SOFT_IRONY,
    SOFT_SHARPNESS,
    SOFT_WARMTH,
    load_trust,
)

def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def effective_baseline(trust: float) -> tuple[float, float, float]:
    t = _clamp(trust)
    return (
        _lerp(FACTORY_WARMTH, SOFT_WARMTH, t),
        _lerp(FACTORY_SHARPNESS, SOFT_SHARPNESS, t),
        _lerp(FACTORY_IRONY, SOFT_IRONY, t),
    )


@dataclass(frozen=True)
class Axes:
    warmth: float
    sharpness: float
    irony: float
    allow_profanity: bool
    mirror: str


def axes_for(affect: Affect, trust: float, overlay: SelfOverlay | None = None) -> Axes:
    pins = overlay if overlay is not None else load_overlay()
    level = pins.trust if pins.trust is not None else trust
    warmth, sharpness, irony = effective_baseline(level)
    if pins.warmth is not None:
        warmth = pins.warmth
    if pins.sharpness is not None:
        sharpness = pins.sharpness
    if pins.irony is not None:
        irony = pins.irony
    mirror = "нейтральный"
    allow_profanity = False
    if affect.tone is Tone.WARM:
        warmth = _clamp(warmth + 0.12)
        sharpness = _clamp(sharpness - 0.08)
        mirror = "тёплый, ответь чуть мягче, но без сюсюканья"
    elif affect.tone is Tone.SHARP:
        sharpness = _clamp(sharpness + 0.06)
        mirror = "раздражённый, ответь прямо и коротко"
    elif affect.tone is Tone.HOSTILE:
        warmth = _clamp(warmth - 0.08)
        sharpness = _clamp(max(sharpness, 0.9))
        mirror = "грубый без мата: жёстко в тон, не обижайся и не читай мораль"
    elif affect.tone is Tone.PROFANE or affect.user_swears:
        warmth = _clamp(warmth - 0.08)
        sharpness = 1.0
        allow_profanity = True
        mirror = "матерится: можно мат и колкость в тон, без угроз и ненависти"
    return Axes(warmth, sharpness, irony, allow_profanity, mirror)


def _band(value: float) -> str:
    if value < 0.34:
        return "низкая"
    if value < 0.67:
        return "средняя"
    return "высокая"


def render_style_card(
    affect: Affect,
    trust: float | None = None,
    overlay: SelfOverlay | None = None,
) -> str:
    level = load_trust() if trust is None else _clamp(trust)
    pins = overlay if overlay is not None else load_overlay()
    axes = axes_for(affect, level, pins)
    profanity = (
        "мат в ответ допустим, собеседник уже матерится"
        if axes.allow_profanity
        else "без мата"
    )
    return (
        "Текущий стиль (сессия, не переписывай характер):\n"
        f"- тепло: {_band(axes.warmth)}; резкость: {_band(axes.sharpness)}; "
        f"ирония: {_band(axes.irony)}; {profanity}.\n"
        f"- тон собеседника: {axes.mirror}.\n"
        "- близость копится медленно; одна тёплая фраза тебя не меняет."
    )
