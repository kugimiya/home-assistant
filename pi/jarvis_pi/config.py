"""Runtime configuration for the Pi edge service."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _parse_wake_words(raw: str) -> tuple[str, ...]:
    words = [part.strip().lower() for part in raw.split(",") if part.strip()]
    return tuple(words) if words else ("компьютер", "джарвис", "прослушка")


@dataclass(frozen=True)
class PiConfig:
    windows_host: str
    pcm_port: int
    control_port: int
    wake_words: tuple[str, ...]
    command_window_sec: float
    arecord_device: str
    aplay_device: str
    sample_rate: int
    location_city: str
    location_district: str
    location_tz: str


def load_location_city() -> str:
    city = os.getenv("LOCATION_CITY", "").strip()
    if city:
        return city
    legacy = os.getenv("WTTR_LOCATION", "").strip()
    if legacy:
        return legacy
    return "Ульяновск"


def load_config() -> PiConfig:
    host = os.getenv("WINDOWS_HOST", "").strip()
    if not host:
        raise ValueError("WINDOWS_HOST is required in .env")

    return PiConfig(
        windows_host=host,
        pcm_port=int(os.getenv("PCM_PORT", "9700")),
        control_port=int(os.getenv("CONTROL_PORT", "9701")),
        wake_words=_parse_wake_words(os.getenv("WAKE_WORDS", "компьютер,джарвис,прослушка")),
        command_window_sec=float(os.getenv("COMMAND_WINDOW_SEC", "10")),
        arecord_device=os.getenv("ARECORD_DEVICE", "plughw:Device,0"),
        aplay_device=os.getenv("APLAY_DEVICE", "default"),
        sample_rate=int(os.getenv("SAMPLE_RATE", "16000")),
        location_city=load_location_city(),
        location_district=os.getenv("LOCATION_DISTRICT", "Ленинский").strip() or "Ленинский",
        location_tz=os.getenv("LOCATION_TZ", "Europe/Samara").strip() or "Europe/Samara",
    )
