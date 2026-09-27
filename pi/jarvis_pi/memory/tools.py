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
    {
        "type": "function",
        "name": "list_memory",
        "description": (
            "Обзор долговременной памяти: сколько фактов и эпизодов в базе и их список "
            "(не поиск по словам). Используй, когда пользователь спрашивает, что ты помнишь, "
            "что сохранено, какие факты или прошлые разговоры записаны."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "facts_limit": {
                    "type": "integer",
                    "description": "Сколько последних фактов перечислить (1–30).",
                },
                "episodes_limit": {
                    "type": "integer",
                    "description": "Сколько последних эпизодов перечислить (1–15).",
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

    if name == "list_memory":
        facts_limit_raw = args.get("facts_limit", 15)
        episodes_limit_raw = args.get("episodes_limit", 10)
        try:
            facts_limit = int(facts_limit_raw)
        except (TypeError, ValueError):
            facts_limit = 15
        try:
            episodes_limit = int(episodes_limit_raw)
        except (TypeError, ValueError):
            episodes_limit = 10
        facts_limit = max(1, min(30, facts_limit))
        episodes_limit = max(1, min(15, episodes_limit))
        inventory = mgr.memory_inventory(
            facts_limit=facts_limit,
            episodes_limit=episodes_limit,
        )
        facts_total = int(inventory["facts_total"])
        episodes_total = int(inventory["episodes_total"])
        if facts_total == 0 and episodes_total == 0:
            return "В памяти пока нет ни фактов, ни эпизодов."
        lines = [
            f"В базе: фактов {facts_total}, эпизодов {episodes_total}.",
        ]
        facts = inventory["facts"]
        if isinstance(facts, list) and facts:
            lines.append("Факты (последние):")
            for item in facts:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("fact_text", ""))
                conf = item.get("confidence", "")
                when = item.get("created_at", "")
                suffix = f", {conf}" if conf else ""
                if when:
                    suffix += f", {when}"
                lines.append(f"- {text}{suffix}")
        episodes = inventory["episodes"]
        if isinstance(episodes, list) and episodes:
            lines.append("Эпизоды (последние диалоги):")
            for item in episodes:
                if not isinstance(item, dict):
                    continue
                summary = str(item.get("summary", ""))
                when = item.get("created_at", "")
                imp = item.get("importance", "")
                extra = f" ({when}, важность {imp})" if when else ""
                lines.append(f"- {summary}{extra}")
        omitted_facts = facts_total - len(facts) if isinstance(facts, list) else 0
        omitted_episodes = episodes_total - len(episodes) if isinstance(episodes, list) else 0
        if omitted_facts > 0:
            lines.append(f"(ещё {omitted_facts} факт(ов) не показано)")
        if omitted_episodes > 0:
            lines.append(f"(ещё {omitted_episodes} эпизод(ов) не показано)")
        return "\n".join(lines)

    return f"Неизвестная функция памяти: {name}"
