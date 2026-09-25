"""One-shot timers via Linux at/atd."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis_pi.config import load_config
from jarvis_pi.sounds_paths import timer_wav

_MIN_SECONDS = 1
_MAX_SECONDS = 86400
_JOB_ID_RE = re.compile(r"job\s+(\d+)", re.IGNORECASE)


def _fire_time_text(duration_seconds: int) -> str:
    config = load_config()
    try:
        now = datetime.now(ZoneInfo(config.location_tz))
    except (OSError, ValueError):
        now = datetime.now()
    fire_at = now + timedelta(seconds=duration_seconds)
    return fire_at.strftime("%H:%M")


def schedule_timer(duration_seconds: int, label: str = "") -> str:
    try:
        duration = int(duration_seconds)
    except (TypeError, ValueError):
        return "Ошибка: duration_seconds должно быть целым числом секунд."

    if duration < _MIN_SECONDS or duration > _MAX_SECONDS:
        return f"Ошибка: длительность от {_MIN_SECONDS} до {_MAX_SECONDS} секунд."

    if shutil.which("at") is None:
        return "Ошибка: команда at не найдена. Установите пакет at и включите atd на Pi."

    sound_path = timer_wav()
    if not sound_path.is_file():
        return f"Ошибка: файл звука таймера не найден: {sound_path}"

    aplay_device = os.getenv("APLAY_DEVICE", "default").strip() or "default"
    at_command = f"aplay -q -D {shlex.quote(aplay_device)} {shlex.quote(str(sound_path))}"

    try:
        completed = subprocess.run(
            ["at", "now", f"+ {duration} seconds"],
            input=at_command + "\n",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Ошибка постановки таймера: {exc}"

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if not detail:
            detail = f"код {completed.returncode}"
        return f"Ошибка постановки таймера: {detail}"

    job_id = ""
    match = _JOB_ID_RE.search(completed.stdout or "")
    if match:
        job_id = match.group(1)

    fire_at = _fire_time_text(duration)
    label_part = f" ({label.strip()})" if label.strip() else ""
    if job_id:
        return (
            f"Таймер #{job_id}{label_part} через {duration} секунд, "
            f"сработает около {fire_at}."
        )
    return f"Таймер{label_part} через {duration} секунд, сработает около {fire_at}."
