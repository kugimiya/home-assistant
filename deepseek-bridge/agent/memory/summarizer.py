"""Session summarization and fact extraction via DeepSeek."""

from __future__ import annotations

import json
import logging
import re

from agent.llm import assistant_message, post_chat
from agent.memory.models import SessionSummaryResult

LOGGER = logging.getLogger("agent.memory.summarizer")

_SUMMARY_PROMPT = """Ты — система управления памятью. Проанализируй диалог и верни только JSON без markdown:

{
  "summary": "Краткое саммари диалога (1-3 предложения)",
  "tags": ["тег1", "тег2"],
  "importance": 75,
  "extracted_facts": [
    {"fact": "...", "confidence": "EXTRACTED"},
    {"fact": "...", "confidence": "INFERRED"}
  ],
  "traits": [
    {"trait": "предпочтение_кофе", "value": "без сахара", "confidence": 0.95}
  ]
}

Правила:
- confidence факта: EXTRACTED — пользователь сказал явно; INFERRED — вывод из контекста; AMBIGUOUS — неоднозначно.
- importance: 0-100.
- tags: нижний регистр.

Диалог:
"""


def _format_dialog(messages: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    for role, content in messages:
        label = "Пользователь" if role == "user" else "Ассистент"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict[str, object] | None:
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def summarize_session(
    messages: list[tuple[str, str]],
    *,
    api_key: str | None = None,
) -> SessionSummaryResult | None:
    del api_key
    if not messages:
        return None
    dialog = _format_dialog(messages)
    payload, err = post_chat(
        [
            {"role": "system", "content": "Верни только JSON без markdown."},
            {"role": "user", "content": _SUMMARY_PROMPT + dialog},
        ],
        temperature=0.2,
        max_tokens=800,
        timeout=45,
    )
    if err is not None or payload is None:
        LOGGER.warning("Session summarization failed: %s", err)
        return None
    message = assistant_message(payload)
    text = ""
    if message is not None and isinstance(message.get("content"), str):
        text = message["content"]
    data = _extract_json(text)
    if not data:
        LOGGER.warning("Session summarization: could not parse model JSON")
        return None
    try:
        return SessionSummaryResult.model_validate(data)
    except Exception:
        LOGGER.warning("Session summarization: schema validation failed")
        return None
