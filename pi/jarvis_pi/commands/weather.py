"""Weather command via wttr.in service."""

from __future__ import annotations

import json
import os
import random
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

from .types import CommandExecutionResult, StreamCallback

TRIGGERS = ("какая погода сейчас", "погода сейчас", "какая погода")

_WTTR_TIMEOUT_SEC = 5


def get_resolve_phrase() -> str:
    options = (
        "Поняла, запрашиваю погоду.",
        "Секунду, проверяю погоду.",
        "Сейчас скажу, какая погода.",
    )
    return random.choice(options)


def _parse_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _degree_word(value: int) -> str:
    last_two = abs(value) % 100
    last = abs(value) % 10
    if 11 <= last_two <= 14:
        return "градусов"
    if last == 1:
        return "градус"
    if 2 <= last <= 4:
        return "градуса"
    return "градусов"


def _speak_temp(value: int) -> str:
    if value > 0:
        prefix = "плюс"
    elif value < 0:
        prefix = "минус"
    else:
        prefix = "ноль"

    if value == 0:
        return f"{prefix} {_degree_word(value)}"
    return f"{prefix} {abs(value)} {_degree_word(value)}"


def _build_url() -> str:
    location = os.getenv("WTTR_LOCATION", "Moscow").strip() or "Moscow"
    encoded_location = quote(location)
    return f"https://wttr.in/{encoded_location}?format=j2&lang=ru"


def handle(payload: str, stream_callback: StreamCallback | None = None) -> CommandExecutionResult:
    del payload, stream_callback
    try:
        with urlopen(_build_url(), timeout=_WTTR_TIMEOUT_SEC) as response:
            payload_data = json.loads(response.read().decode("utf-8"))
    except (TimeoutError, URLError, OSError, json.JSONDecodeError):
        return CommandExecutionResult(reply="Не удалось получить погоду с wttr. Проверьте интернет и попробуйте позже.")

    current = payload_data.get("current_condition", [])
    if not current:
        return CommandExecutionResult(reply="Сервис погоды вернул пустой ответ. Попробуйте позже.")

    condition = current[0]
    temp_c = _parse_int(condition.get("temp_C"))
    feels_like_c = _parse_int(condition.get("FeelsLikeC"))
    weather_desc = ""

    descriptions = condition.get("lang_ru") or condition.get("weatherDesc") or []
    if descriptions and isinstance(descriptions[0], dict):
        weather_desc = (descriptions[0].get("value") or "").strip()

    if temp_c is None:
        return CommandExecutionResult(reply="Не удалось прочитать температуру из ответа сервиса погоды.")

    parts = [f"Сейчас {_speak_temp(temp_c)}"]
    if weather_desc:
        parts.append(weather_desc)
    if feels_like_c is not None:
        parts.append(f"ощущается как {_speak_temp(feels_like_c)}")
    return CommandExecutionResult(reply=". ".join(parts) + ".")
