"""Timer tool. Off by default: the station sets timers itself.

No wake-word dismiss and no local ringing. Those stay on the station.
"""

from __future__ import annotations

_MIN_SECONDS = 1
_MAX_SECONDS = 86400


def schedule_timer(duration_seconds: object, label: str = "") -> str:
    try:
        duration = int(duration_seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "Ошибка: duration_seconds должно быть целым числом секунд."
    if duration < _MIN_SECONDS or duration > _MAX_SECONDS:
        return f"Ошибка: длительность от {_MIN_SECONDS} до {_MAX_SECONDS} секунд."
    label_clean = label.strip()
    label_part = f" ({label_clean})" if label_clean else ""
    return (
        f"Таймер{label_part} на {duration} секунд в прокси не запускается: "
        "звонок остаётся у колонки."
    )
