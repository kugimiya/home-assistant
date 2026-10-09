"""Personality axes, profanity ceiling, and slow trust."""

from __future__ import annotations

import pytest

from jarvis_pi.personality.affect import Tone, classify
from jarvis_pi.personality.prompt import IDENTITY_INSTRUCTIONS
from jarvis_pi.personality.state import (
    note_user_affect,
    reset_session_marks,
    save_trust,
    trust_after_session,
)
from jarvis_pi.personality.style import axes_for, effective_baseline, render_style_card


def test_identity_is_not_a_snowflake() -> None:
    text = IDENTITY_INSTRUCTIONS.lower()
    assert "не снежинка" in text
    assert "женск" in text
    assert "piper" in text


def test_factory_baseline_is_dry() -> None:
    warmth, sharpness, irony = effective_baseline(0.0)
    assert warmth < 0.34
    assert sharpness > 0.67
    assert 0.34 <= irony < 0.67
    card = render_style_card(classify("который час"), trust=0.0)
    assert "тепло: низкая" in card
    assert "резкость: высокая" in card
    assert "без мата" in card


def test_profanity_only_when_user_swears() -> None:
    hostile = classify("ты тупая, заткнись")
    assert hostile.tone is Tone.HOSTILE
    assert hostile.user_swears is False
    axes = axes_for(hostile, 0.0)
    assert axes.allow_profanity is False
    assert "без мата" in render_style_card(hostile, trust=0.0)

    profane = classify("да иди нахуй блять")
    assert profane.tone is Tone.PROFANE
    assert profane.user_swears is True
    profane_axes = axes_for(profane, 0.0)
    assert profane_axes.allow_profanity is True
    assert "мат в ответ допустим" in render_style_card(profane, trust=0.0)


def test_one_warm_turn_barely_moves_trust(tmp_path) -> None:
    path = tmp_path / "personality.json"
    save_trust(0.0, path)
    reset_session_marks()
    note_user_affect(classify("спасибо, ты молодец"))
    from jarvis_pi.personality.state import on_session_end

    updated = on_session_end(path)
    assert updated == 0.0
    assert trust_after_session(0.2, turns=1, warm_turns=1) == 0.2


def test_warm_session_steps_trust_slowly() -> None:
    nudged = trust_after_session(0.2, turns=4, warm_turns=3)
    assert nudged == pytest.approx(0.24)
    capped = trust_after_session(0.99, turns=4, warm_turns=4)
    assert capped == 1.0
    hostile_session = trust_after_session(0.4, turns=5, warm_turns=0)
    assert hostile_session == 0.4
