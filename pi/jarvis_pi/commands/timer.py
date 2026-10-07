"""Voice assistant countdown timers (in-process)."""

from __future__ import annotations

from jarvis_pi.timer_service import TimerService

_service: TimerService | None = None


def configure(service: TimerService) -> None:
    global _service
    _service = service


def schedule_timer(duration_seconds: int, label: str = "") -> str:
    if _service is None:
        return "Ошибка: сервис таймеров не инициализирован."
    return _service.schedule(duration_seconds, label=label)
