"""Set ALSA playback and capture volume via amixer."""

from __future__ import annotations

import os
import shutil
import subprocess

_MIN_PERCENT = 0
_MAX_PERCENT = 100


def _parse_percent(value: object) -> int | str:
    if isinstance(value, bool):
        return "Ошибка: громкость должна быть целым числом от 0 до 100."
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Ошибка: громкость должна быть целым числом от 0 до 100."
    if not number.is_integer():
        return "Ошибка: громкость должна быть целым числом от 0 до 100."
    percent = int(number)
    if percent < _MIN_PERCENT or percent > _MAX_PERCENT:
        return "Ошибка: громкость должна быть от 0 до 100."
    return percent


def mixer_device(pcm_device: str) -> str:
    """Map a PCM device (aplay/arecord -D) to an amixer simple mixer device."""
    device = pcm_device.strip() or "default"
    lowered = device.lower()
    for prefix in ("plughw:", "hw:", "sysdefault:", "plug:"):
        if lowered.startswith(prefix):
            card = device[len(prefix) :].split(",")[0].strip()
            if card:
                return f"hw:{card}"
    return device


def _control_name(env_name: str, default: str) -> str:
    return os.getenv(env_name, default).strip() or default


def _set_volume(pcm_device: str, control: str, percent: int, label: str) -> str:
    if shutil.which("amixer") is None:
        return "Ошибка: команда amixer не найдена. Установите alsa-utils на Pi."

    mixer = mixer_device(pcm_device)
    try:
        completed = subprocess.run(
            ["amixer", "-D", mixer, "sset", control, f"{percent}%"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Ошибка установки громкости {label}: {exc}"

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if not detail:
            detail = f"код {completed.returncode}"
        return f"Ошибка установки громкости {label}: {detail}"

    return f"Громкость {label} установлена на {percent} процентов (устройство {mixer}, контроль {control})."


def set_speaker_volume(percent: object) -> str:
    parsed = _parse_percent(percent)
    if isinstance(parsed, str):
        return parsed
    device = os.getenv("APLAY_DEVICE", "default").strip() or "default"
    control = _control_name("SPEAKER_ALSA_CONTROL", "Speaker")
    return _set_volume(device, control, parsed, "колонки")


def set_mic_volume(percent: object) -> str:
    parsed = _parse_percent(percent)
    if isinstance(parsed, str):
        return parsed
    device = os.getenv("ARECORD_DEVICE", "plughw:Device,0").strip() or "plughw:Device,0"
    control = _control_name("MIC_ALSA_CONTROL", "Mic")
    return _set_volume(device, control, parsed, "микрофона")
