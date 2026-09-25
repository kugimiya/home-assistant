"""Weather tool via wttr.in service."""

from __future__ import annotations

import json
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

from jarvis_pi.config import load_location_city

_WTTR_TIMEOUT_SEC = 5


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
    location = load_location_city()
    encoded_location = quote(location)
    return f"https://wttr.in/{encoded_location}?format=j2&lang=ru"


def fetch_weather_text() -> str:
    try:
        with urlopen(_build_url(), timeout=_WTTR_TIMEOUT_SEC) as response:
            payload_data = json.loads(response.read().decode("utf-8"))
    except (TimeoutError, URLError, OSError, json.JSONDecodeError):
        return "Не удалось получить погоду с wttr. Проверьте интернет и попробуйте позже."

    current = payload_data.get("current_condition", [])
    if not current:
        return "Сервис погоды вернул пустой ответ. Попробуйте позже."

    condition = current[0]
    temp_c = _parse_int(condition.get("temp_C"))
    feels_like_c = _parse_int(condition.get("FeelsLikeC"))
    weather_desc = ""

    descriptions = condition.get("lang_ru") or condition.get("weatherDesc") or []
    if descriptions and isinstance(descriptions[0], dict):
        weather_desc = (descriptions[0].get("value") or "").strip()

    if temp_c is None:
        return "Не удалось прочитать температуру из ответа сервиса погоды."

    parts = [f"Сейчас {_speak_temp(temp_c)}"]
    if weather_desc:
        parts.append(weather_desc)
    if feels_like_c is not None:
        parts.append(f"ощущается как {_speak_temp(feels_like_c)}")
    return ". ".join(parts) + "."
