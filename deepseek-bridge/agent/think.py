"""One-shot tool loop for a station utterance. No wake, STT, or TTS."""

from __future__ import annotations

import re
from datetime import datetime

from agent.catalog import chat_tools, enabled_tool_names, execute
from agent.config import (
    MAX_TOOL_ROUNDS,
    MODEL_MAX_TOKENS,
    MODEL_TIMEOUT_SEC,
    SPOKEN_CHAR_LIMIT,
    load_location_city,
    location_district,
    location_tz,
    tool_enabled,
)
from agent.llm import assistant_message, post_chat
from agent.personality.affect import classify
from agent.personality.overlay import render_overlay_block
from agent.personality.prompt import IDENTITY_INSTRUCTIONS
from agent.personality.state import note_user_affect
from agent.personality.style import render_style_card

_HISTORY = 8


class Reply:
    def __init__(self, text: str = "", error: int | str | None = None, end_session: bool = False) -> None:
        self.text = text
        self.error = error
        self.end_session = end_session


def log(msg: str) -> None:
    print(msg.replace("\n", " "), flush=True)


def _memory():
    try:
        from agent.memory import get_memory_manager

        return get_memory_manager()
    except Exception as exc:
        log(f"memory unavailable {type(exc).__name__}")
        return None


def build_instructions(last_user_text: str = "") -> str:
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(location_tz()))
    except Exception:
        now = datetime.now()
    when = now.strftime("%d.%m.%Y %H:%M")

    memory_section = ""
    if last_user_text.strip():
        memory = _memory()
        if memory is not None:
            try:
                block = memory.get_context_for_prompt(last_user_text)
            except Exception as exc:
                log(f"memory context failed {type(exc).__name__}")
                block = ""
            if block:
                memory_section = (
                    "\n\nДолговременная память (можно уточнить через search_memory):\n"
                    f"{block}\n"
                )

    lines = [
        "Ты домашний голосовой помощник в колонке. Не отвечай с Markdown-разметкой: "
        "колонка озвучит звёздочки. Числа и цифры пиши текстом. ",
        f"Ограничения генерации. Один ход модели: не больше {MODEL_MAX_TOKENS} токенов "
        f"и {MODEL_TIMEOUT_SEC} секунд, иначе ответ обрывается. "
        f"Инструменты — не больше {MAX_TOOL_ROUNDS} раундов. "
        f"Вслух уходит не больше {SPOKEN_CHAR_LIMIT} символов: хвост отрезается и не озвучивается. "
        "Пиши ответ короче этого предела. ",
        f"Сейчас {when}. Город: {load_location_city()}. Район: {location_district()}. "
        f"Часовой пояс: {location_tz()} (для run_python: zoneinfo.ZoneInfo('{location_tz()}')). ",
        "Для погоды вызывай инструмент get_weather. ",
        "Для свежих фактов из интернета вызывай web_search — не отказывайся от поиска, "
        "если пользователь просит найти или узнать актуальное. ",
        "Для расчётов и любого Python, который надо выполнить, вызывай run_python: "
        "напиши код с print() и озвучь напечатанное своими словами, сам код вслух не читай. ",
        "Когда спрашивают, как ты устроена, что делает Яндекс, DeepSeek или колонка, "
        "вызывай describe_runtime и пересказывай его текст. Архитектуру не выдумывай. ",
        "Для воспоминаний о пользователе и прошлых разговорах вызывай search_memory; "
        "если пользователь просит запомнить факт — add_memory (confidence EXTRACTED для явных фраз). ",
        "Профиль: get_profile. Что сохранено в памяти целиком (факты и эпизоды): list_memory. "
        "Отдельно последние эпизоды: get_recent_episodes. "
        "Чтобы создать, изменить или удалить факт, черту или эпизод — memory_crud. ",
        "Чтобы переписать свой характер или добавку к инструкциям — rewrite_self. "
        "Чтобы сбросить только эти самоправки к заводскому характеру — reset_self "
        "(память пользователя при этом остаётся). ",
        "Если пользователь хочет завершить разговор (спи, выключись, всё) — вызывай decline, "
        "без прощальной речи в ответе. ",
        "Если инструмент вернул ошибку, коротко объясни её суть своими словами. "
        "Не зачитывай код, трассировку и сырой текст ошибки. ",
    ]
    if tool_enabled("set_timer"):
        lines.append("Для таймеров вызывай set_timer (длительность в секундах). ")
    if tool_enabled("set_speaker_volume") or tool_enabled("set_mic_volume"):
        lines.append(
            "Для громкости колонки вызывай set_speaker_volume, для микрофона set_mic_volume "
            "(целое число процентов от 0 до 100). "
        )
    if tool_enabled("get_home") or tool_enabled("control_home"):
        lines.append(
            "Для умного дома вызывай get_home, чтобы узнать состояние, и control_home, "
            "чтобы включить, выключить или переключить свет и другие устройства. "
            "В target передавай слова пользователя («зал 2», «свет в зале»), не выдумывай entity_id. "
        )
    lines.append(IDENTITY_INSTRUCTIONS + " ")
    lines.append(render_style_card(classify(last_user_text)))
    lines.append(render_overlay_block())
    lines.append(memory_section)
    lines.append(
        "Имя в озвучке только латиницей: Alice. "
        "По-русски «Алиса» не пиши и не говори: колонка произнесёт wake-фразу и ответ сломается. "
    )
    return "".join(lines)


def _tool_calls(message: dict[str, object]) -> list[dict[str, object]]:
    raw = message.get("tool_calls")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _echo_assistant(message: dict[str, object]) -> dict[str, object]:
    echoed: dict[str, object] = {
        "role": "assistant",
        "content": message.get("content"),
    }
    calls = _tool_calls(message)
    if calls:
        echoed["tool_calls"] = calls
    reasoning = message.get("reasoning_content")
    if reasoning:
        echoed["reasoning_content"] = reasoning
    return echoed


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def answer(text: str, history: list[dict[str, object]]) -> Reply:
    prompt = text.strip()
    if not prompt:
        return Reply("Пусто. Повтори нормально.")

    memory = _memory()
    if memory is not None:
        try:
            memory.ensure_session()
        except Exception as exc:
            log(f"memory session failed {type(exc).__name__}")
            memory = None
    affect = classify(prompt)
    note_user_affect(affect)

    prior = [item for item in history[-_HISTORY:] if isinstance(item, dict)]
    messages: list[dict[str, object]] = [
        {"role": "system", "content": build_instructions(prompt)},
        *prior,
        {"role": "user", "content": prompt},
    ]
    tools = chat_tools()
    log("tools " + ",".join(enabled_tool_names()))

    try:
        for _ in range(MAX_TOOL_ROUNDS + 1):
            payload, err = post_chat(messages, tools=tools)
            if err is not None or payload is None:
                return Reply(error=err or "bad_response")
            message = assistant_message(payload)
            if message is None:
                return Reply(error="bad_response")
            calls = _tool_calls(message)
            if calls:
                messages.append(_echo_assistant(message))
                decline = False
                for call in calls:
                    call_id = str(call.get("id") or "").strip()
                    function = call.get("function")
                    if not isinstance(function, dict):
                        function = {}
                    name = str(function.get("name") or "").strip()
                    arguments = str(function.get("arguments") or "{}")
                    if not call_id or not name:
                        continue
                    log(f"tool {name}")
                    result, is_decline = execute(name, arguments)
                    if is_decline:
                        decline = True
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": result,
                        }
                    )
                if decline:
                    if memory is not None:
                        try:
                            memory.record_user_only(prompt)
                            memory.end_session(summarize=True)
                        except Exception as exc:
                            log(f"memory decline failed {type(exc).__name__}")
                    return Reply(end_session=True)
                continue

            content = message.get("content")
            full = _clean(content if isinstance(content, str) else "")
            if not full:
                return Reply("DeepSeek вернул пустой ответ.")
            if memory is not None:
                try:
                    memory.record_exchange(prompt, full)
                    memory.touch_interaction()
                except Exception as exc:
                    log(f"memory record failed {type(exc).__name__}")
            return Reply(full)
        return Reply("Слишком много шагов с инструментами, попробуй проще.")
    except Exception as exc:
        log(f"agent failed {type(exc).__name__}")
        return Reply(error=type(exc).__name__)
