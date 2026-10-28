"""Persistent trust. The model cannot rewrite it."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from agent.personality.affect import Affect, Tone

_LOCK = threading.RLock()

FACTORY_WARMTH = 0.12
FACTORY_SHARPNESS = 0.88
FACTORY_IRONY = 0.55
SOFT_WARMTH = 0.62
SOFT_SHARPNESS = 0.42
SOFT_IRONY = 0.48

_TRUST_STEP = 0.04
_MIN_WARM_TURNS = 2
_WARM_RATIO = 0.5


def _data_path() -> Path:
    raw = os.getenv("PERSONALITY_PATH", "").strip()
    if raw:
        return Path(raw)
    from agent.memory.config import load_memory_config

    return load_memory_config().db_path.parent / "personality.json"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def load_trust(path: Path | None = None) -> float:
    target = path or _data_path()
    if not target.exists():
        return 0.0
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    if not isinstance(payload, dict):
        return 0.0
    try:
        return _clamp(float(payload.get("trust", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def save_trust(trust: float, path: Path | None = None) -> None:
    target = path or _data_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"trust": round(_clamp(trust), 4)}, ensure_ascii=False)
    target.write_text(body + "\n", encoding="utf-8")


class _SessionMarks:
    def __init__(self) -> None:
        self.turns = 0
        self.warm = 0

    def note(self, affect: Affect) -> None:
        self.turns += 1
        if affect.tone is Tone.WARM:
            self.warm += 1

    def take(self) -> tuple[int, int]:
        snapshot = (self.turns, self.warm)
        self.turns = 0
        self.warm = 0
        return snapshot


_MARKS = _SessionMarks()


def note_user_affect(affect: Affect) -> None:
    with _LOCK:
        _MARKS.note(affect)


def trust_after_session(trust: float, turns: int, warm_turns: int) -> float:
    """Small upward step only for a clearly warm session. Rudeness does not drop trust."""
    if turns < _MIN_WARM_TURNS or warm_turns < _MIN_WARM_TURNS:
        return _clamp(trust)
    if warm_turns / turns < _WARM_RATIO:
        return _clamp(trust)
    return _clamp(trust + _TRUST_STEP)


def on_session_end(path: Path | None = None) -> float:
    with _LOCK:
        turns, warm = _MARKS.take()
        current = load_trust(path)
        updated = trust_after_session(current, turns, warm)
        if updated != current:
            save_trust(updated, path)
        return updated


def reset_session_marks() -> None:
    with _LOCK:
        _MARKS.take()
