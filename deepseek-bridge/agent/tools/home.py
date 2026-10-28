"""Home Assistant device list and control."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_CATALOG_TEMPLATE = """
{% set domains = ['light', 'switch', 'fan', 'cover', 'climate', 'scene', 'script'] %}
{% for domain in domains %}
{% for s in states[domain] %}
{% set did = device_id(s.entity_id) %}
{% set device = device_attr(did, 'name_by_user') or device_attr(did, 'name') if did else '' %}
{{ s.entity_id }}|{{ s.name }}|{{ area_name(s.entity_id) or '' }}|{{ device or '' }}|{{ s.state }}|{{ s.attributes.brightness | default('', true) }}|{{ s.attributes.color_temp_kelvin | default('', true) }}
{% endfor %}
{% endfor %}
""".strip()

_DOMAIN_WORDS = {
    "свет": "light",
    "лампа": "light",
    "лампы": "light",
    "лампу": "light",
    "лампочка": "light",
    "лампочку": "light",
    "лампочки": "light",
    "люстра": "light",
    "люстру": "light",
    "розетка": "switch",
    "розетку": "switch",
    "розетки": "switch",
}
_FILLER = {"в", "во", "на", "у", "и", "все", "всё", "весь", "вся", "всех"}
_ACTIONS = {"turn_on": "Включил", "turn_off": "Выключил", "toggle": "Переключил"}


@dataclass(frozen=True)
class HomeEntity:
    entity_id: str
    name: str
    device_name: str
    area: str
    state: str
    brightness: str = ""
    color_temp_kelvin: str = ""

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    def label(self) -> str:
        return self.device_name or self.name or self.entity_id


def get_home(target: str = "") -> str:
    entities, error = _load_entities()
    if error:
        return error
    if not entities:
        return "В Home Assistant нет управляемых устройств."
    chosen, resolve_error = resolve_targets(entities, target) if target.strip() else (entities, None)
    if resolve_error:
        return resolve_error
    return _format_entities(chosen)


def control_home(
    target: object,
    action: object,
    brightness_pct: object = None,
    color_temp_kelvin: object = None,
) -> str:
    action_name = str(action or "").strip()
    if action_name not in _ACTIONS:
        return "Ошибка: action должен быть turn_on, turn_off или toggle."
    target_text = str(target or "").strip()
    if not target_text:
        return "Ошибка: не указано устройство или зона."
    brightness, brightness_error = _optional_int(brightness_pct, "brightness_pct", 0, 100)
    if brightness_error:
        return brightness_error
    color_temp, color_error = _optional_int(color_temp_kelvin, "color_temp_kelvin", 1000, 10000)
    if color_error:
        return color_error

    entities, error = _load_entities()
    if error:
        return error
    chosen, resolve_error = resolve_targets(entities, target_text)
    if resolve_error:
        return resolve_error
    if not chosen:
        return f"Не нашёл «{target_text}»."

    payload: dict[str, object] = {"entity_id": [item.entity_id for item in chosen]}
    if brightness is not None:
        payload["brightness_pct"] = brightness
    if color_temp is not None:
        payload["color_temp_kelvin"] = color_temp
    domain = chosen[0].domain
    if any(item.domain != domain for item in chosen):
        domain = "homeassistant"
    service_error = _call_service(domain, action_name, payload)
    if service_error:
        return service_error
    names = ", ".join(item.label() for item in chosen)
    return f"{_ACTIONS[action_name]}: {names}."


def resolve_targets(
    entities: list[HomeEntity], query: str
) -> tuple[list[HomeEntity], str | None]:
    domain, remainder = _split_query(query)
    pool = [item for item in entities if item.domain == domain] if domain else list(entities)
    if not pool:
        return [], f"Нет устройств типа «{query}»."
    if not remainder:
        return pool, None

    exact = [item for item in pool if _exact_names(item) & {remainder}]
    if exact:
        return exact, None

    if any(_area_phrase(remainder, item.area) for item in pool):
        return [item for item in pool if _area_phrase(remainder, item.area)], None

    partial = [
        item
        for item in pool
        if any(remainder in name or name in remainder for name in _exact_names(item) if name)
    ]
    if len(partial) == 1:
        return partial, None
    if len(partial) > 1:
        listed = ", ".join(item.label() for item in partial)
        return [], f"Несколько устройств подходят под «{query}»: {listed}."
    return [], f"Не нашёл «{query}»."


def _area_phrase(remainder: str, area: str) -> bool:
    normalized = _norm(area)
    if not normalized or not remainder:
        return False
    if remainder == normalized:
        return True
    # «зале», «залом» — падеж сразу после названия зоны, без лишних слов.
    return " " not in remainder and remainder.startswith(normalized) and len(remainder) - len(normalized) <= 3


def _exact_names(item: HomeEntity) -> set[str]:
    names = {_norm(item.device_name), _norm(item.name), _norm(item.entity_id)}
    names.add(_norm(item.entity_id.replace(".", " ").replace("_", " ")))
    names.discard("")
    return names


def _split_query(query: str) -> tuple[str | None, str]:
    domain: str | None = None
    words: list[str] = []
    for word in _norm(query).split():
        hinted = _DOMAIN_WORDS.get(word)
        if hinted:
            domain = hinted
            continue
        if word in _FILLER:
            continue
        words.append(word)
    return domain, " ".join(words)


def _norm(text: str) -> str:
    cleaned = text.lower().replace("ё", "е").replace("_", " ").replace("-", " ")
    cleaned = re.sub(r"[^a-zа-я0-9\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _format_entities(entities: list[HomeEntity]) -> str:
    lines: list[str] = []
    for item in entities:
        place = item.area or "без зоны"
        details = _state_text(item)
        lines.append(f"{place}: {item.label()} ({item.entity_id}) — {details}")
    return "\n".join(lines)


def _state_text(item: HomeEntity) -> str:
    state = item.state
    if state in {"on", "off"}:
        text = "включен" if state == "on" else "выключен"
    elif state in {"unavailable", "unknown", ""}:
        text = "недоступен"
    else:
        text = state
    if item.brightness.isdigit():
        percent = round(int(item.brightness) * 100 / 255)
        text += f", яркость {percent}%"
    if item.color_temp_kelvin.isdigit():
        text += f", {item.color_temp_kelvin} К"
    return text


def _optional_int(value: object, name: str, low: int, high: int) -> tuple[int | None, str | None]:
    if value is None or value == "":
        return None, None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None, f"Ошибка: {name} должен быть целым числом."
    try:
        number = int(str(value).strip())
    except ValueError:
        return None, f"Ошибка: {name} должен быть целым числом."
    if number < low or number > high:
        return None, f"Ошибка: {name} должен быть от {low} до {high}."
    return number, None


def _load_entities() -> tuple[list[HomeEntity], str | None]:
    base, token, error = _credentials()
    if error:
        return [], error
    status, body = _request("POST", f"{base}/api/template", {"template": _CATALOG_TEMPLATE}, token)
    if status == 200 and body.strip():
        parsed = _parse_catalog(body)
        if parsed:
            return parsed, None
    status, body = _request("GET", f"{base}/api/states", None, token)
    if status != 200:
        return [], _http_failure(status, body)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return [], "Home Assistant вернул непонятный список устройств."
    if not isinstance(payload, list):
        return [], "Home Assistant вернул непонятный список устройств."
    entities: list[HomeEntity] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id", ""))
        if entity_id.split(".", 1)[0] not in {"light", "switch", "fan", "cover", "climate", "scene", "script"}:
            continue
        attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        brightness = attributes.get("brightness", "")
        color_temp = attributes.get("color_temp_kelvin", "")
        entities.append(
            HomeEntity(
                entity_id=entity_id,
                name=str(attributes.get("friendly_name") or entity_id),
                device_name=str(attributes.get("friendly_name") or ""),
                area="",
                state=str(item.get("state", "")),
                brightness="" if brightness is None else str(brightness),
                color_temp_kelvin="" if color_temp is None else str(color_temp),
            )
        )
    return entities, None


def _parse_catalog(body: str) -> list[HomeEntity]:
    entities: list[HomeEntity] = []
    for line in body.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 5 or "." not in parts[0]:
            continue
        entities.append(
            HomeEntity(
                entity_id=parts[0],
                name=parts[1],
                device_name=parts[3],
                area=parts[2],
                state=parts[4],
                brightness=parts[5] if len(parts) > 5 else "",
                color_temp_kelvin=parts[6] if len(parts) > 6 else "",
            )
        )
    return entities


def _call_service(domain: str, service: str, payload: dict[str, object]) -> str | None:
    base, token, error = _credentials()
    if error:
        return error
    status, body = _request("POST", f"{base}/api/services/{domain}/{service}", payload, token)
    if status in {200, 201}:
        return None
    return _http_failure(status, body)


def _credentials() -> tuple[str, str, str | None]:
    base = os.getenv("HA_URL", "http://127.0.0.1").strip().rstrip("/") or "http://127.0.0.1"
    token = os.getenv("HA_TOKEN", "").strip()
    if not token:
        return base, "", "Не настроен HA_TOKEN в .env."
    return base, token, None


def _request(method: str, url: str, payload: dict[str, object] | None, token: str) -> tuple[int, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, detail
    except URLError as exc:
        return 0, str(exc.reason)


def _http_failure(status: int, body: str) -> str:
    if status == 0:
        return f"Home Assistant недоступен: {body}"
    if status == 401:
        return "Home Assistant отклонил токен."
    text = body.strip().replace("\n", " ")
    if text:
        return f"Home Assistant вернул ошибку {status}: {text[:200]}"
    return f"Home Assistant вернул ошибку {status}."
