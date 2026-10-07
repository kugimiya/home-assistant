"""In-process countdown timers with long ring and wake-to-dismiss."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis_pi.config import load_config
from jarvis_pi.wake import text_contains_wake_word

LOGGER = logging.getLogger("jarvis_pi.timer_service")

_MIN_SECONDS = 1
_MAX_SECONDS = 86400
_DEFAULT_RING_SEC = 300.0


def _ring_duration_sec() -> float:
    raw = os.getenv("TIMER_RING_DURATION_SEC", "300").strip()
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_RING_SEC
    return max(1.0, value)


def _fire_time_text(duration_seconds: int) -> str:
    config = load_config()
    try:
        now = datetime.now(ZoneInfo(config.location_tz))
    except (OSError, ValueError):
        now = datetime.now()
    fire_at = now + timedelta(seconds=duration_seconds)
    return fire_at.strftime("%H:%M")


@dataclass
class TimerService:
    aplay_device: str
    timer_sound: Path
    wake_words: tuple[str, ...]
    ring_duration_sec: float = field(default_factory=_ring_duration_sec)
    engine: object | None = None

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 0
        self._ringing = False
        self._stop_event = threading.Event()
        self._alarm_thread: threading.Thread | None = None

    def is_ringing(self) -> bool:
        with self._lock:
            return self._ringing

    def schedule(self, duration_seconds: int, label: str = "") -> str:
        try:
            duration = int(duration_seconds)
        except (TypeError, ValueError):
            return "Ошибка: duration_seconds должно быть целым числом секунд."

        if duration < _MIN_SECONDS or duration > _MAX_SECONDS:
            return f"Ошибка: длительность от {_MIN_SECONDS} до {_MAX_SECONDS} секунд."

        if not self.timer_sound.is_file():
            return f"Ошибка: файл звука таймера не найден: {self.timer_sound}"

        with self._lock:
            self._next_id += 1
            timer_id = self._next_id

        label_clean = label.strip()
        delay_timer = threading.Timer(
            duration,
            self._on_timer_fire,
            args=(timer_id, label_clean),
        )
        delay_timer.daemon = True
        delay_timer.start()

        fire_at = _fire_time_text(duration)
        label_part = f" ({label_clean})" if label_clean else ""
        return (
            f"Таймер #{timer_id}{label_part} через {duration} секунд, "
            f"сработает около {fire_at}."
        )

    def wake_dismisses_ring(self, text: str, *, is_final: bool) -> bool:
        if not is_final:
            return False
        if not self.is_ringing():
            return False
        return text_contains_wake_word(text, self.wake_words)

    def stop_ringing(self) -> bool:
        with self._lock:
            if not self._ringing:
                return False
            self._stop_event.set()
            engine = self.engine
            thread = self._alarm_thread
        if engine is not None and hasattr(engine, "stop_playback"):
            engine.stop_playback()
        if thread and thread.is_alive():
            thread.join(timeout=3.0)
        else:
            with self._lock:
                self._ringing = False
        return True

    def _on_timer_fire(self, timer_id: int, label: str) -> None:
        label_part = f" ({label})" if label else ""
        LOGGER.info("Timer #%s fired%s — starting ring loop", timer_id, label_part)
        with self._lock:
            if self._ringing:
                LOGGER.info("Timer ring already active (timer #%s joins it)", timer_id)
                return
            self._ringing = True
            self._stop_event.clear()
            self._alarm_thread = threading.Thread(
                target=self._alarm_loop,
                name=f"timer-ring-{timer_id}",
                daemon=True,
            )
            self._alarm_thread.start()

    def _alarm_loop(self) -> None:
        deadline = time.monotonic() + self.ring_duration_sec
        try:
            while time.monotonic() < deadline:
                if self._stop_event.is_set():
                    break
                if self.engine is not None:
                    finished = bool(self.engine.play_wav(self.timer_sound))
                else:
                    from jarvis_pi.audio_io import play_wav_until_stopped

                    finished = play_wav_until_stopped(
                        self.aplay_device,
                        self.timer_sound,
                        self._stop_event,
                    )
                if not finished or self._stop_event.is_set():
                    break
        finally:
            with self._lock:
                self._ringing = False
                self._alarm_thread = None
            LOGGER.info("Timer ring finished (stopped=%s)", self._stop_event.is_set())
