import time

from jarvis_pi.barge_in import BargeInDetector
from jarvis_pi.near_end import NearEndSpeechGate, pcm_rms
from jarvis_pi.playback_timeline import PlaybackTimeline
from jarvis_pi.resample import resample_s16_mono


def test_resample_22050_to_16000_shrinks() -> None:
    pcm = (b"\x00\x10" * 22050)
    out = resample_s16_mono(pcm, 22050, 16000)
    assert abs(len(out) // 2 - 16000) <= 2


def test_timeline_covers_wake_inside_span() -> None:
    timeline = PlaybackTimeline()
    timeline.note("скажи джарвис ещё раз", 5.0, now=100.0)
    assert timeline.covers_wake_word("джарвис", now=101.0)
    assert not timeline.covers_wake_word("компьютер", now=101.0)


def test_barge_in_uses_remote_text_not_local_model() -> None:
    timeline = PlaybackTimeline()
    hits: list[str] = []
    detector = BargeInDetector(
        wake_words=("компьютер",),
        timeline=timeline,
        on_trigger=lambda: hits.append("go"),
    )
    detector.set_enabled(True)
    detector._near_until = time.monotonic() + 5
    assert detector.consider("компьютер", is_final=True)
    assert hits == ["go"]
    timeline.note("это компьютер", 5.0, now=time.monotonic())
    detector.set_enabled(True)
    detector._near_until = time.monotonic() + 5
    assert not detector.consider("компьютер", is_final=True)


def test_near_end_gate_requires_energy() -> None:
    gate = NearEndSpeechGate(threshold=500, ratio=1.2)
    silence = b"\x00\x00" * 160
    loud = (b"\xff\x0f" * 160)
    assert pcm_rms(silence) < 10
    assert not gate.allows(silence, silence)
    assert gate.allows(loud, silence)
