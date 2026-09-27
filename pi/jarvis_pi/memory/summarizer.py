"""Session summarization and fact extraction via DeepSeek."""

from __future__ import annotations

import json
import logging
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jarvis_pi.memory.models import SessionSummaryResult

LOGGER = logging.getLogger("jarvis_pi.memory.summarizer")

_DEFAULT_RESPONSES_URL = "https://api.deepseek.com/responses"
_DEFAULT_MODEL = "deepseek-flash"
_REQUEST_TIMEOUT_SEC = 120

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


def _responses_url() -> str:
    return os.getenv("DEEPSEEK_RESPONSES_URL", _DEFAULT_RESPONSES_URL).strip() or _DEFAULT_RESPONSES_URL


def _model() -> str:
    return os.getenv("DEEPSEEK_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


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


def _text_from_response(response: dict[str, object]) -> str:
    output = response.get("output")
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "output_text":
                parts.append(str(part.get("text", "")))
    return "".join(parts).strip()


def summarize_session(
    messages: list[tuple[str, str]],
    *,
    api_key: str | None = None,
) -> SessionSummaryResult | None:
    if not messages:
        return None
    key = (api_key or os.getenv("DEEPSEEK_API_KEY", "")).strip()
    if not key:
        LOGGER.warning("Cannot summarize session: DEEPSEEK_API_KEY missing")
        return None

    dialog = _format_dialog(messages)
    instructions = _SUMMARY_PROMPT + dialog
    body: dict[str, object] = {
        "model": _model(),
        "instructions": instructions,
        "input": [{"role": "user", "content": "Верни JSON по схеме из инструкции."}],
        "stream": False,
        "tools": [],
        "temperature": 0.2,
    }
    request = Request(
        _responses_url(),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=_REQUEST_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        LOGGER.warning("Session summarization failed: %s", type(exc).__name__)
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        LOGGER.warning("Session summarization: invalid JSON response")
        return None

    if not isinstance(payload, dict):
        return None

    text = _text_from_response(payload)
    if not text and isinstance(payload.get("output_text"), str):
        text = str(payload["output_text"])

    data = _extract_json(text)
    if not data:
        LOGGER.warning("Session summarization: could not parse model JSON")
        return None

    try:
        return SessionSummaryResult.model_validate(data)
    except Exception:
        LOGGER.warning("Session summarization: schema validation failed")
        return None
