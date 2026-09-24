"""Think command with free-form payload."""

from __future__ import annotations

import json
import os
import random
import re
from collections import deque
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .types import CommandExecutionResult, StreamCallback

TRIGGERS = ("подумай",)
_DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
_DEEPSEEK_MODEL = "deepseek-chat"
_REQUEST_TIMEOUT_SEC = 60
_MAX_INTERACTIONS = 5
_CONTEXT_MESSAGES: deque[dict[str, str]] = deque(maxlen=_MAX_INTERACTIONS * 2)
_ABBREVIATION_TAILS = (
    "т.д.",
    "т.п.",
    "т.е.",
    "и т.д.",
    "и т.п.",
    "и др.",
    "и пр.",
    "г.",
    "ул.",
    "рис.",
)

resolve_options = (
    "Ща подумаю",
    "Угу, запускаю мыслительный процесс, подожди",
    "Спрашиваю у дипсика",
    "Понятен запрос, подожди",
)


def get_resolve_phrase() -> str:
    return random.choice(resolve_options)


def get_fallback_resolve_phrase() -> str:
    return random.choice(resolve_options)


def _strip_markdown_for_tts(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"(^|\s)#{1,6}\s*", r"\1", cleaned)
    cleaned = re.sub(r"(^|\s)[*_~-]{1,3}(?=\S)", r"\1", cleaned)
    cleaned = re.sub(r"(?<=\S)[*_~-]{1,3}(?=\s|$)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_text_delta(delta_content: object) -> str:
    if isinstance(delta_content, str):
        return delta_content
    if isinstance(delta_content, list):
        parts: list[str] = []
        for item in delta_content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text = str(item.get("text", ""))
                if text:
                    parts.append(text)
        return "".join(parts)
    return ""


def _context_messages() -> list[dict[str, str]]:
    return [dict(message) for message in _CONTEXT_MESSAGES]


def _is_sentence_boundary(buffer: str, idx: int) -> bool:
    char = buffer[idx]
    if char not in ".!?":
        return False

    prefix = buffer[: idx + 1].rstrip().lower()
    if any(prefix.endswith(abbrev) for abbrev in _ABBREVIATION_TAILS):
        return False

    if (
        char == "."
        and idx > 0
        and idx + 1 < len(buffer)
        and buffer[idx - 1].isdigit()
        and buffer[idx + 1].isdigit()
    ):
        return False

    if idx + 1 >= len(buffer):
        return True

    next_char = buffer[idx + 1]
    if next_char == "\n":
        return True
    if next_char.isspace():
        tail = buffer[idx + 1 :].lstrip()
        return not tail or tail[0].isupper() or tail[0].isdigit() or tail[0] in "\"'«("
    return False


def _emit_sentences(buffer: str, stream_callback: StreamCallback | None) -> tuple[str, list[str]]:
    if not stream_callback:
        return buffer, []

    emitted: list[str] = []
    for idx, char in enumerate(buffer):
        if char in ".!?" and _is_sentence_boundary(buffer, idx):
            split_index = idx + 1
            sentence = buffer[:split_index].strip()
            if sentence:
                spoken = _strip_markdown_for_tts(sentence)
                if spoken:
                    stream_callback(spoken)
                    emitted.append(spoken)
            buffer = buffer[split_index:].lstrip()
            rest_buffer, rest_emitted = _emit_sentences(buffer, stream_callback)
            return rest_buffer, emitted + rest_emitted
    return buffer, emitted


def handle(payload: str, stream_callback: StreamCallback | None = None) -> CommandExecutionResult:
    prompt = payload.strip()
    if not prompt:
        return CommandExecutionResult(reply="Сформулируй, о чем подумать после команды.")

    system_prompt = (
        "Ты домашний голосовой помощник в колонке. Старайся отвечать средне "
        "(не кратко, но и не через чур длинно). Не отвечай с Markdown-разметкой, "
        "TTS озвучивает всякие звезда-звезда. Разные числа и цифры пиши текстом, "
        "TTS плохо их склоняет."
    )
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return CommandExecutionResult(reply="Не настроен DEEPSEEK_API_KEY в .env.")

    body = {
        "model": _DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            *_context_messages(),
            {"role": "user", "content": prompt},
        ],
        "stream": True,
    }
    request = Request(
        _DEEPSEEK_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=_REQUEST_TIMEOUT_SEC) as response:
            chunks: list[str] = []
            sentence_buffer = ""
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("data:"):
                    continue

                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break

                event = json.loads(data)
                choices = event.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                piece = _extract_text_delta(delta.get("content"))
                if not piece:
                    continue
                chunks.append(piece)
                sentence_buffer += piece
                sentence_buffer, _ = _emit_sentences(sentence_buffer, stream_callback)

            full_text = "".join(chunks).strip()
            if not full_text:
                return CommandExecutionResult(reply="DeepSeek вернул пустой ответ.")

            remainder = sentence_buffer.strip()
            if remainder and stream_callback:
                spoken_remainder = _strip_markdown_for_tts(remainder)
                if spoken_remainder:
                    stream_callback(spoken_remainder)

            sanitized_full_text = _strip_markdown_for_tts(full_text) or full_text
            _CONTEXT_MESSAGES.append({"role": "user", "content": prompt})
            _CONTEXT_MESSAGES.append({"role": "assistant", "content": sanitized_full_text})
            return CommandExecutionResult(
                reply=sanitized_full_text,
                spoken_during_handle=stream_callback is not None,
            )
    except HTTPError as exc:
        return CommandExecutionResult(reply=f"DeepSeek вернул ошибку {exc.code}.")
    except TimeoutError:
        return CommandExecutionResult(reply="Не получилось получить ответ от DeepSeek: таймаут")
    except URLError:
        return CommandExecutionResult(reply="Не получилось получить ответ от DeepSeek: ошибка адреса")
    except OSError:
        return CommandExecutionResult(reply="Не получилось получить ответ от DeepSeek: ошибка операционной системы")
    except json.JSONDecodeError:
        return CommandExecutionResult(reply="Не получилось получить ответ от DeepSeek: ошибка парсинга джей сон")
