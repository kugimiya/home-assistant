from pathlib import Path

from jarvis_pi.timer_service import TimerService


def test_schedule_returns_russian_confirmation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WINDOWS_HOST", "127.0.0.1")
    sound = tmp_path / "timer.wav"
    sound.write_bytes(b"RIFF")
    svc = TimerService(
        aplay_device="default",
        timer_sound=sound,
        wake_words=("компьютер",),
        ring_duration_sec=60.0,
    )
    msg = svc.schedule(120, label="чай")
    assert "Таймер #1" in msg
    assert "120" in msg
    assert "чай" in msg


def test_wake_dismiss_only_on_final_while_ringing(tmp_path: Path) -> None:
    sound = tmp_path / "timer.wav"
    sound.write_bytes(b"RIFF")
    svc = TimerService(
        aplay_device="default",
        timer_sound=sound,
        wake_words=("компьютер",),
        ring_duration_sec=60.0,
    )
    with svc._lock:
        svc._ringing = True
    assert not svc.wake_dismisses_ring("компьютер", is_final=False)
    assert svc.wake_dismisses_ring("компьютер", is_final=True)
    assert not svc.wake_dismisses_ring("привет", is_final=True)


def test_stop_ringing_clears_flag(tmp_path: Path) -> None:
    sound = tmp_path / "timer.wav"
    sound.write_bytes(b"RIFF")
    svc = TimerService(
        aplay_device="default",
        timer_sound=sound,
        wake_words=("компьютер",),
        ring_duration_sec=60.0,
    )
    assert not svc.stop_ringing()
    with svc._lock:
        svc._ringing = True
    svc._stop_event.clear()
    assert svc.stop_ringing()
    assert not svc.is_ringing()
