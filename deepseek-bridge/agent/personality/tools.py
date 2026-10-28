"""Tools that let the model rewrite itself and roll that back."""

from __future__ import annotations

import json

from agent.personality.overlay import SelfOverlay, clear_overlay, load_overlay, save_overlay
from agent.personality.state import reset_session_marks, save_trust

SELF_RESPONSES_TOOLS: list[dict[str, object]] = [
    {
        "type": "function",
        "name": "rewrite_self",
        "description": (
            "Переписать свой характер и добавку к инструкциям. Заводской baseline остаётся, "
            "это слой поверх. Память пользователя не трогает. Можно передать только нужные поля."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "character": {
                    "type": "string",
                    "description": "Как ты себя ведёшь дальше. Пустая строка стирает этот слой.",
                },
                "prompt_extra": {
                    "type": "string",
                    "description": "Дополнительные инструкции себе. Пустая строка стирает их.",
                },
                "warmth": {"type": "number", "description": "0–1, закрепить тепло."},
                "sharpness": {"type": "number", "description": "0–1, закрепить резкость."},
                "irony": {"type": "number", "description": "0–1, закрепить иронию."},
                "trust": {"type": "number", "description": "0–1, закрепить близость."},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "reset_self",
        "description": (
            "Сбросить всё, что ты накрутила в характере и инструкциях, к заводскому baseline. "
            "Память пользователя (факты, профиль, эпизоды) не удаляется."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


def _opt_float(args: dict[str, object], key: str) -> float | None:
    if key not in args or args[key] is None:
        return None
    try:
        return max(0.0, min(1.0, float(args[key])))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def execute_self_tool(name: str, args: dict[str, object]) -> str:
    if name == "reset_self":
        clear_overlay()
        save_trust(0.0)
        reset_session_marks()
        return "Характер и самоправки инструкций сброшены. Память на месте."

    if name == "rewrite_self":
        current = load_overlay()
        if "character" in args:
            current.character = str(args.get("character") or "")
        if "prompt_extra" in args:
            current.prompt_extra = str(args.get("prompt_extra") or "")
        for key in ("warmth", "sharpness", "irony", "trust"):
            if key in args:
                setattr(current, key, _opt_float(args, key))
        if current.trust is not None:
            save_trust(current.trust)
        if current.is_empty():
            clear_overlay()
        else:
            save_overlay(
                SelfOverlay(
                    character=current.character,
                    prompt_extra=current.prompt_extra,
                    warmth=current.warmth,
                    sharpness=current.sharpness,
                    irony=current.irony,
                    trust=current.trust,
                )
            )
        return "Самоправка записана и действует со следующего ответа.\n" + json.dumps(
            {
                "character": current.character,
                "prompt_extra": current.prompt_extra,
                "warmth": current.warmth,
                "sharpness": current.sharpness,
                "irony": current.irony,
                "trust": current.trust,
            },
            ensure_ascii=False,
        )

    return f"Неизвестная функция характера: {name}"
