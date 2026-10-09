"""DeepSeek Responses API agent with function tools."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from jarvis_pi.config import load_config
from jarvis_pi.memory import (
    MEMORY_CRUD_TOOL,
    MEMORY_RESPONSES_TOOLS,
    execute_memory_crud,
    execute_memory_tool,
    get_memory_manager,
)
from jarvis_pi.personality import (
    IDENTITY_INSTRUCTIONS,
    classify,
    note_user_affect,
    render_style_card,
)
from jarvis_pi.personality.overlay import render_overlay_block
from jarvis_pi.personality.tools import SELF_RESPONSES_TOOLS, execute_self_tool

from . import python_runner
from . import timer as timer_tool
from . import volume as volume_tool
from . import web_search as web_search_tool
from . import weather
from .types import CommandExecutionResult, StreamCallback

_DEFAULT_RESPONSES_URL = "https://api.deepseek.com/responses"
_DEFAULT_MODEL = "deepseek-flash"
_REQUEST_TIMEOUT_SEC = 120
_MAX_TURNS = 8
_MAX_TOOL_ROUNDS = 6
# Each turn: user message + model/tool output items for the next request.
_TURNS: list[tuple[dict[str, object], list[dict[str, object]]]] = []


def _clear_turns() -> None:
    _TURNS.clear()


get_memory_manager().set_clear_turns_callback(_clear_turns)
_FOLLOWUP_MARKER = "[[AWAIT_USER]]"
_DONE_MARKER = "[[DONE]]"

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

_RESPONSES_TOOLS: list[dict[str, object]] = [
    {
        "type": "function",
        "name": "get_weather",
        "description": "Текущая погода в городе пользователя.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "web_search",
        "description": (
            "Поиск актуальной информации в интернете: новости, курсы, расписания, "
            "факты, которые могли измениться."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос на русском или английском.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "set_timer",
        "description": (
            "Поставить звуковой таймер на заданное число секунд. "
            "Переводи минуты и часы в секунды сам."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "duration_seconds": {
                    "type": "integer",
                    "description": "Через сколько секунд проиграть звук таймера (1–86400).",
                },
                "label": {
                    "type": "string",
                    "description": "Короткое описание таймера для пользователя.",
                },
            },
            "required": ["duration_seconds"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "set_speaker_volume",
        "description": (
            "Установить громкость вывода (колонка, ALSA-контроль Speaker) "
            "на устройстве воспроизведения. Проценты от 0 до 100."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "percent": {
                    "type": "integer",
                    "description": "Громкость колонки от 0 до 100.",
                }
            },
            "required": ["percent"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "set_mic_volume",
        "description": (
            "Установить громкость ввода (микрофон, ALSA-контроль Mic) "
            "на устройстве записи. Проценты от 0 до 100."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "percent": {
                    "type": "integer",
                    "description": "Громкость микрофона от 0 до 100.",
                }
            },
            "required": ["percent"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "run_python",
        "description": (
            "Выполнить короткий Python для точных вычислений: проценты, деление, "
            "сколько времени до указанного часа. Код должен print() результат."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python-код; результат только через print().",
                }
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "decline",
        "description": (
            "Завершить диалог и уйти в режим ожидания, когда пользователь прощается "
            "или просит замолчать: спи, выключись, всё, хватит, отбой."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    *MEMORY_RESPONSES_TOOLS,
    MEMORY_CRUD_TOOL,
    *SELF_RESPONSES_TOOLS,
]


def _responses_url() -> str:
    return os.getenv("DEEPSEEK_RESPONSES_URL", _DEFAULT_RESPONSES_URL).strip() or _DEFAULT_RESPONSES_URL


def _model() -> str:
    return os.getenv("DEEPSEEK_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _reasoning_body() -> dict[str, str]:
    if not _env_flag("DEEPSEEK_REASONING", False):
        return {"effort": "none"}
    effort = os.getenv("DEEPSEEK_REASONING_EFFORT", "low").strip().lower() or "low"
    allowed = {"low", "high", "max", "minimal", "medium", "xhigh"}
    if effort not in allowed:
        effort = "low"
    return {"effort": effort}


def _build_instructions(last_user_text: str = "", *, user_affect_text: str = "") -> str:
    config = load_config()
    try:
        now = datetime.now(ZoneInfo(config.location_tz))
    except (OSError, ValueError):
        now = datetime.now()
    when = now.strftime("%d.%m.%Y %H:%M")

    memory_block = ""
    if last_user_text.strip():
        memory_block = get_memory_manager().get_context_for_prompt(last_user_text)
    memory_section = ""
    if memory_block:
        memory_section = f"\n\nДолговременная память (можно уточнить через search_memory):\n{memory_block}\n"

    return (
        "Ты домашний голосовой помощник в колонке. Старайся отвечать средне "
        "(не кратко, но и не длинно). Не отвечай с Markdown-разметкой, "
        "TTS озвучивает всякие звезда-звезда. Разные числа и цифры пиши текстом, "
        "TTS плохо их склоняет. "
        f"Сейчас {when}. Город: {config.location_city}. Район: {config.location_district}. "
        f"Часовой пояс: {config.location_tz} (для run_python: zoneinfo.ZoneInfo('{config.location_tz}')). "
        "Для погоды вызывай инструмент get_weather. "
        "Для свежих фактов из интернета вызывай web_search — не отказывайся от поиска, "
        "если пользователь просит найти или узнать актуальное. "
        "Для таймеров вызывай set_timer (длительность в секундах); "
        "после срабатывания звук идёт несколько минут, пользователь может "
        "остановить wake-фразой. "
        "Для громкости колонки вызывай set_speaker_volume, для микрофона set_mic_volume "
        "(целое число процентов от 0 до 100). "
        "Для арифметики, процентов и «сколько до …» вызывай run_python — не считай в уме, "
        "пиши код с print() и озвучь результат своими словами. "
        "Для воспоминаний о пользователе и прошлых разговорах вызывай search_memory; "
        "если пользователь просит запомнить факт — add_memory (confidence EXTRACTED для явных фраз). "
        "Профиль: get_profile. Что сохранено в памяти целиком (факты и эпизоды): list_memory. "
        "Отдельно последние эпизоды: get_recent_episodes. "
        "Чтобы создать, изменить или удалить факт, черту или эпизод — memory_crud. "
        "Чтобы переписать свой характер или добавку к инструкциям — rewrite_self. "
        "Чтобы сбросить только эти самоправки к заводскому характеру — reset_self "
        "(память пользователя при этом остаётся). "
        "Если пользователь хочет завершить разговор (спи, выключись, всё) — вызывай decline, "
        "без прощальной речи в ответе. "
        "После ответа колонка по умолчанию снова ждёт wake-фразу. "
        "Если без ответа пользователя нельзя продолжить — ты что-то не понял, нужно уточнение, "
        "задаёшь вопрос или просишь повторить — в самом конце текста добавь маркер "
        f"{_FOLLOWUP_MARKER} (его не озвучивай). "
        "Если задача выполнена (таймер, погода, поиск, громкость, расчёт, факт из памяти) "
        f"и уточнений не нужно — маркер не добавляй или добавь {_DONE_MARKER}. "
        f"{IDENTITY_INSTRUCTIONS} "
        f"{render_style_card(classify(user_affect_text or last_user_text))}"
        f"{render_overlay_block()}"
        f"{memory_section}"
    )


def _strip_followup_markers(text: str) -> str:
    cleaned = text.replace(_FOLLOWUP_MARKER, "").replace(_DONE_MARKER, "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _followup_from_markers(raw_text: str) -> bool | None:
    if _FOLLOWUP_MARKER in raw_text:
        return True
    if _DONE_MARKER in raw_text:
        return False
    return None


def _implicit_await_followup(reply: str) -> bool:
    lowered = reply.strip().lower()
    if not lowered:
        return False
    if "повтори" in lowered and ("не расслыш" in lowered or "уточн" in lowered):
        return True
    if lowered.endswith("?"):
        return True
    return False


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


def _build_request_input(prompt: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    user_item: dict[str, object] = {"role": "user", "content": prompt}
    items: list[dict[str, object]] = []
    for user_message, output_items in _TURNS:
        items.append(user_message)
        items.extend(output_items)
    items.append(user_item)
    return user_item, items


def _commit_turn(user_item: dict[str, object], output_items: list[dict[str, object]]) -> None:
    _TURNS.append((user_item, output_items))
    while len(_TURNS) > _MAX_TURNS:
        _TURNS.pop(0)


def _text_from_output_items(output_items: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for item in output_items:
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "output_text":
                text = str(part.get("text", ""))
                if text:
                    parts.append(text)
    return "".join(parts).strip()


def _function_calls_from_output(output_items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [item for item in output_items if item.get("type") == "function_call"]


def _execute_function_call(name: str, arguments_json: str) -> tuple[str, bool]:
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict):
        args = {}

    if name == "decline":
        return "Сессия будет завершена.", True
    if name == "get_weather":
        return weather.fetch_weather_text(), False
    if name == "web_search":
        query = str(args.get("query", "")).strip()
        if not query:
            return "Ошибка: пустой поисковый запрос.", False
        return web_search_tool.search(query), False
    if name == "set_timer":
        label = str(args.get("label", ""))
        duration_raw = args.get("duration_seconds", 0)
        return timer_tool.schedule_timer(duration_raw, label=label), False
    if name == "set_speaker_volume":
        return volume_tool.set_speaker_volume(args.get("percent")), False
    if name == "set_mic_volume":
        return volume_tool.set_mic_volume(args.get("percent")), False
    if name == "run_python":
        code = str(args.get("code", ""))
        return python_runner.run_python(code), False
    if name in (
        "search_memory",
        "add_memory",
        "get_profile",
        "get_recent_episodes",
        "list_memory",
    ):
        return execute_memory_tool(name, args), False
    if name == "memory_crud":
        return execute_memory_crud(args), False
    if name in ("rewrite_self", "reset_self"):
        return execute_self_tool(name, args), False
    return f"Неизвестная функция: {name}", False


def _iter_response_events(response) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
            continue
        if "data:" in line and line.startswith("event:"):
            _, rest = line.split("event:", 1)
            data_idx = rest.find("data:")
            if data_idx == -1:
                continue
            payload = rest[data_idx + 5 :].strip()
            if not payload:
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _output_text_delta(event: dict[str, object]) -> str:
    if event.get("type") != "response.output_text.delta":
        return ""
    delta = event.get("delta")
    return delta if isinstance(delta, str) else ""


def _final_response_from_events(events: list[dict[str, object]]) -> dict[str, object] | None:
    for event in reversed(events):
        event_type = event.get("type")
        if event_type in ("response.completed", "response.incomplete", "response.failed"):
            response = event.get("response")
            if isinstance(response, dict):
                return response
    return None


def _output_items_from_response(response: dict[str, object] | None) -> list[dict[str, object]]:
    if not response:
        return []
    output_raw = response.get("output")
    output_items: list[dict[str, object]] = []
    if isinstance(output_raw, list):
        for item in output_raw:
            if isinstance(item, dict):
                output_items.append(item)
    return output_items


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


def _http_error_message(exc: HTTPError) -> str:
    detail = ""
    try:
        body = exc.read().decode("utf-8", errors="ignore")
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            err = parsed.get("error")
            if isinstance(err, dict) and err.get("message"):
                detail = str(err["message"])
            elif parsed.get("message"):
                detail = str(parsed["message"])
        if not detail:
            detail = body[:240]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    if detail:
        return f"DeepSeek вернул ошибку {exc.code}: {detail}"
    return f"DeepSeek вернул ошибку {exc.code}."


def _speak_full_text(full_text: str, stream_callback: StreamCallback | None) -> None:
    if not stream_callback or not full_text.strip():
        return
    buffer = full_text
    buffer, _ = _emit_sentences(buffer, stream_callback)
    remainder = buffer.strip()
    if remainder:
        spoken_remainder = _strip_markdown_for_tts(remainder)
        if spoken_remainder:
            stream_callback(spoken_remainder)


def _post_responses(
    api_key: str,
    request_input: list[dict[str, object]],
    *,
    last_user_text: str = "",
    user_affect_text: str = "",
) -> tuple[dict[str, object] | None, str, bool]:
    body: dict[str, object] = {
        "model": _model(),
        "instructions": _build_instructions(
            last_user_text, user_affect_text=user_affect_text
        ),
        "input": request_input,
        "stream": True,
        "tool_choice": "auto",
        "tools": _RESPONSES_TOOLS,
        "reasoning": _reasoning_body(),
    }
    request = Request(
        _responses_url(),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urlopen(request, timeout=_REQUEST_TIMEOUT_SEC) as response:
        events = _iter_response_events(response)
        chunks: list[str] = []
        for event in events:
            piece = _output_text_delta(event)
            if not piece:
                continue
            chunks.append(piece)

        final_response = _final_response_from_events(events)
        output_items = _output_items_from_response(final_response)
        has_function_calls = bool(_function_calls_from_output(output_items))

        full_text = "".join(chunks).strip() or _text_from_output_items(output_items)
        return final_response, full_text, has_function_calls


def _finalize_reply(
    raw_text: str,
    *,
    spoken_during_handle: bool = False,
) -> CommandExecutionResult:
    marker_hint = _followup_from_markers(raw_text)
    stripped = _strip_followup_markers(raw_text)
    sanitized = _strip_markdown_for_tts(stripped) or stripped
    if marker_hint is not None:
        await_followup = marker_hint
    else:
        await_followup = _implicit_await_followup(sanitized)
    return CommandExecutionResult(
        reply=sanitized,
        spoken_during_handle=spoken_during_handle,
        await_followup=await_followup,
    )


def handle(payload: str, stream_callback: StreamCallback | None = None) -> CommandExecutionResult:
    prompt = payload.strip()
    if not prompt:
        return CommandExecutionResult(
            reply="Пусто. Повтори нормально.",
            await_followup=True,
        )

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return CommandExecutionResult(reply="Не настроен DEEPSEEK_API_KEY в .env.")

    memory = get_memory_manager()
    memory.ensure_session()
    affect = classify(prompt)
    note_user_affect(affect)

    user_item, request_input = _build_request_input(prompt)
    turn_history_items: list[dict[str, object]] = []
    spoken_during_handle = False

    try:
        for _ in range(_MAX_TOOL_ROUNDS + 1):
            final_response, full_text, has_function_calls = _post_responses(
                api_key,
                request_input,
                last_user_text=prompt,
                user_affect_text=prompt,
            )

            if final_response and final_response.get("status") == "failed":
                err = final_response.get("error")
                message = "неизвестная ошибка"
                if isinstance(err, dict) and err.get("message"):
                    message = str(err["message"])
                return CommandExecutionResult(reply=f"DeepSeek не смог ответить: {message}")

            output_items = _output_items_from_response(final_response)
            if not output_items and not full_text:
                return CommandExecutionResult(reply="DeepSeek вернул пустой ответ.")

            if has_function_calls:
                request_input.extend(output_items)
                turn_history_items.extend(output_items)
                decline_requested = False
                for call in _function_calls_from_output(output_items):
                    call_id = str(call.get("call_id") or call.get("id") or "").strip()
                    name = str(call.get("name") or "").strip()
                    arguments = str(call.get("arguments") or "{}")
                    if not call_id:
                        continue
                    result, is_decline = _execute_function_call(name, arguments)
                    if is_decline:
                        decline_requested = True
                    tool_output: dict[str, object] = {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result,
                    }
                    request_input.append(tool_output)
                    turn_history_items.append(tool_output)
                if decline_requested:
                    memory.record_user_only(prompt)
                    memory.end_session(summarize=True)
                    return CommandExecutionResult(reply="", end_session=True)
                continue

            speak_text = _strip_followup_markers(full_text)
            sanitized_full_text = _strip_markdown_for_tts(speak_text) or speak_text
            if not sanitized_full_text:
                return CommandExecutionResult(reply="DeepSeek вернул пустой ответ.")

            turn_history_items.extend(output_items)
            _commit_turn(user_item, turn_history_items)
            memory.record_exchange(prompt, sanitized_full_text)
            memory.touch_interaction()
            if stream_callback is not None:
                _speak_full_text(speak_text, stream_callback)
                spoken_during_handle = True
            return _finalize_reply(full_text, spoken_during_handle=spoken_during_handle)

        return CommandExecutionResult(reply="Слишком много шагов с инструментами, попробуй проще.")
    except HTTPError as exc:
        return CommandExecutionResult(reply=_http_error_message(exc))
    except TimeoutError:
        return CommandExecutionResult(reply="Не получилось получить ответ от DeepSeek: таймаут")
    except URLError:
        return CommandExecutionResult(reply="Не получилось получить ответ от DeepSeek: ошибка адреса")
    except OSError:
        return CommandExecutionResult(reply="Не получилось получить ответ от DeepSeek: ошибка операционной системы")
    except json.JSONDecodeError:
        return CommandExecutionResult(reply="Не получилось получить ответ от DeepSeek: ошибка парсинга джей сон")
