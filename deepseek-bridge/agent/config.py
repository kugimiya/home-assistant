"""Settings for the station agent. Not shared with the Pi DeepSeek client."""

from __future__ import annotations

import os

TOKEN_FILE = os.environ.get(
    "DEEPSEEK_TOKEN_FILE", "/data/quasar/deepseek-bridge/token"
)
CHAT_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
# One model call, then the spoken cut in bridge.speakable.
MODEL_MAX_TOKENS = 800
MODEL_TIMEOUT_SEC = 45
MAX_TOOL_ROUNDS = 6
SPOKEN_CHAR_LIMIT = 500

# The station already performs these. They stay off so the model cannot take
# them. Enable later with BRIDGE_TOOL_<NAME>=1 when replacing that handler.
# Smart home is not in this list: get_home and control_home stay on.
STATION_TOOLS = (
    "set_timer",
    "set_speaker_volume",
    "set_mic_volume",
)


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def tool_enabled(name: str) -> bool:
    if name in STATION_TOOLS:
        return env_flag(f"BRIDGE_TOOL_{name.upper()}", False)
    return True


def load_location_city() -> str:
    city = os.getenv("LOCATION_CITY", "").strip()
    if city:
        return city
    legacy = os.getenv("WTTR_LOCATION", "").strip()
    if legacy:
        return legacy
    return "Ульяновск"


def location_district() -> str:
    return os.getenv("LOCATION_DISTRICT", "Ленинский").strip() or "Ленинский"


def location_tz() -> str:
    return os.getenv("LOCATION_TZ", "Europe/Samara").strip() or "Europe/Samara"


def model_name() -> str:
    return os.getenv("BRIDGE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def load_token() -> str:
    with open(TOKEN_FILE, "r", encoding="utf-8") as handle:
        token = handle.read().strip()
    if not token:
        raise RuntimeError("empty token file")
    return token
