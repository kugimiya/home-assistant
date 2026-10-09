"""Model-written self overlay. Factory identity stays in code."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

_MAX_TEXT = 1500


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clip(text: str) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:_MAX_TEXT]


def overlay_path() -> Path:
    raw = os.getenv("PERSONALITY_OVERLAY_PATH", "").strip()
    if raw:
        return Path(raw)
    from jarvis_pi.memory.config import load_memory_config

    return load_memory_config().db_path.parent / "self_overlay.json"


@dataclass
class SelfOverlay:
    character: str = ""
    prompt_extra: str = ""
    warmth: float | None = None
    sharpness: float | None = None
    irony: float | None = None
    trust: float | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.character,
                self.prompt_extra,
                self.warmth is not None,
                self.sharpness is not None,
                self.irony is not None,
                self.trust is not None,
            )
        )


def _opt_float(payload: dict[str, object], key: str) -> float | None:
    if key not in payload or payload[key] is None:
        return None
    try:
        return _clamp(float(payload[key]))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def load_overlay(path: Path | None = None) -> SelfOverlay:
    target = path or overlay_path()
    if not target.exists():
        return SelfOverlay()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SelfOverlay()
    if not isinstance(payload, dict):
        return SelfOverlay()
    return SelfOverlay(
        character=_clip(str(payload.get("character") or "")),
        prompt_extra=_clip(str(payload.get("prompt_extra") or "")),
        warmth=_opt_float(payload, "warmth"),
        sharpness=_opt_float(payload, "sharpness"),
        irony=_opt_float(payload, "irony"),
        trust=_opt_float(payload, "trust"),
    )


def save_overlay(overlay: SelfOverlay, path: Path | None = None) -> None:
    target = path or overlay_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "character": _clip(overlay.character),
        "prompt_extra": _clip(overlay.prompt_extra),
        "warmth": overlay.warmth,
        "sharpness": overlay.sharpness,
        "irony": overlay.irony,
        "trust": overlay.trust,
    }
    target.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clear_overlay(path: Path | None = None) -> None:
    target = path or overlay_path()
    if target.exists():
        target.unlink()


def render_overlay_block(overlay: SelfOverlay | None = None) -> str:
    current = overlay if overlay is not None else load_overlay()
    parts: list[str] = []
    if current.character:
        parts.append("Самоправка характера (твоя, действует поверх baseline):\n" + current.character)
    if current.prompt_extra:
        parts.append("Самоправка инструкций (твоя):\n" + current.prompt_extra)
    if not parts:
        return ""
    return "\n\n" + "\n\n".join(parts) + "\n"
