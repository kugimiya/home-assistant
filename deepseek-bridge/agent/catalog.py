"""Tool schemas and dispatch. Station-native tools are filtered by config."""

from __future__ import annotations

import json

from agent.config import tool_enabled
from agent.memory.tools import (
    MEMORY_CRUD_TOOL,
    MEMORY_RESPONSES_TOOLS,
    execute_memory_crud,
    execute_memory_tool,
)
from agent.personality.tools import SELF_RESPONSES_TOOLS, execute_self_tool
from agent.tools import home as home_tool
from agent.tools import python_runner, timer, volume, weather, web_search

_OFF = "Эта функция выключена: её выполняет сама колонка."

_CORE: list[dict[str, object]] = [
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
]

_STATION: list[dict[str, object]] = [
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
            "Установить громкость вывода колонки. Проценты от 0 до 100."
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
            "Установить громкость микрофона. Проценты от 0 до 100."
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
        "name": "get_home",
        "description": (
            "Список устройств умного дома и их состояние: свет, розетки, зоны. "
            "Вызывай перед ответом, что включено, и если не уверен в имени устройства."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Необязательно: зона или устройство, чтобы сузить список.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "control_home",
        "description": (
            "Включить, выключить или переключить устройство или всю зону в умном доме. "
            "target — имя устройства или зоны, как его сказал пользователь "
            "(«зал 2», «свет в зале»). Яркость и цвет только если пользователь просит."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Устройство, зона или «свет».",
                },
                "action": {
                    "type": "string",
                    "enum": ["turn_on", "turn_off", "toggle"],
                    "description": "turn_on включить, turn_off выключить, toggle переключить.",
                },
                "brightness_pct": {
                    "type": "integer",
                    "description": "Яркость 0–100, только если пользователь назвал уровень.",
                },
                "color_temp_kelvin": {
                    "type": "integer",
                    "description": "Цветовая температура в кельвинах, только если пользователь просит теплее или холоднее.",
                },
            },
            "required": ["target", "action"],
            "additionalProperties": False,
        },
    },
]


def _all_specs() -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    specs.extend(_CORE)
    specs.extend(MEMORY_RESPONSES_TOOLS)
    specs.append(MEMORY_CRUD_TOOL)
    specs.extend(SELF_RESPONSES_TOOLS)
    specs.extend(_STATION)
    return specs


def enabled_specs() -> list[dict[str, object]]:
    return [spec for spec in _all_specs() if tool_enabled(str(spec["name"]))]


def enabled_tool_names() -> list[str]:
    return [str(spec["name"]) for spec in enabled_specs()]


def chat_tools() -> list[dict[str, object]]:
    tools: list[dict[str, object]] = []
    for spec in enabled_specs():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec["parameters"],
                },
            }
        )
    return tools


def execute(name: str, arguments_json: str) -> tuple[str, bool]:
    try:
        return _execute(name, arguments_json)
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        text = f"Ошибка инструмента {name}: {type(exc).__name__}: {detail}"
        return text[:800], False


def _execute(name: str, arguments_json: str) -> tuple[str, bool]:
    if not tool_enabled(name):
        return _OFF, False
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
        return web_search.search(query), False
    if name == "run_python":
        return python_runner.run_python(str(args.get("code", ""))), False
    if name == "set_timer":
        return timer.schedule_timer(args.get("duration_seconds", 0), label=str(args.get("label", ""))), False
    if name == "set_speaker_volume":
        return volume.set_speaker_volume(args.get("percent")), False
    if name == "set_mic_volume":
        return volume.set_mic_volume(args.get("percent")), False
    if name == "get_home":
        return home_tool.get_home(str(args.get("target", ""))), False
    if name == "control_home":
        return home_tool.control_home(
            args.get("target"),
            args.get("action"),
            args.get("brightness_pct"),
            args.get("color_temp_kelvin"),
        ), False
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
