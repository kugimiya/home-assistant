"""DeepSeek Responses API tool schemas and execution for memory."""

from __future__ import annotations

import json

from jarvis_pi.memory.manager import get_memory_manager

MEMORY_RESPONSES_TOOLS: list[dict[str, object]] = [
    {
        "type": "function",
        "name": "search_memory",
        "description": (
            "Поиск в долговременной памяти: факты, прошлые диалоги (эпизоды), черты профиля. "
            "Используй, когда нужны сведения из прошлых разговоров или сохранённые факты."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос на русском или английском.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Максимум результатов (1–20).",
                },
                "layer": {
                    "type": "string",
                    "enum": ["hot", "warm", "cold", "all"],
                    "description": "Временной слой: hot — 3ч, warm — до 7 дней, cold — старше.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "add_memory",
        "description": (
            "Сохранить факт в долговременную память. Используй, когда пользователь просит "
            "запомнить что-то или явно сообщает устойчивый факт о себе."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "Текст факта для сохранения."},
                "source": {
                    "type": "string",
                    "enum": ["user_explicit", "model_inferred"],
                },
                "confidence": {
                    "type": "string",
                    "enum": ["EXTRACTED", "INFERRED", "AMBIGUOUS"],
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["fact"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_profile",
        "description": "Получить все сохранённые черты и предпочтения пользователя.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_recent_episodes",
        "description": "Последние саммари завершённых диалогов с датами.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Сколько эпизодов вернуть (1–10).",
                },
            },
            "additionalProperties": False,
        },
    },
]


def execute_memory_tool(name: str, args: dict[str, object]) -> str:
    mgr = get_memory_manager()
    if name == "search_memory":
        query = str(args.get("query", "")).strip()
        if not query:
            return "Ошибка: пустой запрос поиска."
        limit_raw = args.get("limit", 5)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(20, limit))
        layer = str(args.get("layer", "all")).strip().lower()
        if layer not in ("hot", "warm", "cold", "all"):
            layer = "all"
        hits = mgr.search(query, layer=layer, limit=limit)
        if not hits:
            return "Ничего не найдено в памяти."
        lines = [
            f"{i + 1}. [{h.channel}] {h.text}"
            + (f" ({h.created_at})" if h.created_at else "")
            for i, h in enumerate(hits)
        ]
        return "Результаты поиска:\n" + "\n".join(lines)

    if name == "add_memory":
        fact = str(args.get("fact", "")).strip()
        if not fact:
            return "Ошибка: пустой факт."
        source = str(args.get("source", "user_explicit")).strip() or "user_explicit"
        confidence = str(args.get("confidence", "EXTRACTED")).strip() or "EXTRACTED"
        tags_raw = args.get("tags")
        tags: list[str] | None = None
        if isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        fact_id = mgr.add_fact(fact, source=source, confidence=confidence, tags=tags)
        return f"Факт сохранён (id={fact_id})."

    if name == "get_profile":
        profile = mgr.get_profile()
        if not profile:
            return "Профиль пуст."
        return json.dumps(profile, ensure_ascii=False, indent=2)

    if name == "get_recent_episodes":
        limit_raw = args.get("limit", 3)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 3
        limit = max(1, min(10, limit))
        episodes = mgr.get_recent_episodes(limit=limit)
        if not episodes:
            return "Эпизодов пока нет."
        return json.dumps(episodes, ensure_ascii=False, indent=2)

    return f"Неизвестная функция памяти: {name}"
