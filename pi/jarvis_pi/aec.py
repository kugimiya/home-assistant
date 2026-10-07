"""Echo cancellation. WebRTC APM when installed, otherwise passthrough."""

from __future__ import annotations

import logging
import os

LOGGER = logging.getLogger("jarvis_pi.aec")


class EchoCanceller:
    def process(self, near: bytes, far: bytes) -> bytes:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return "base"


class PassthroughEchoCanceller(EchoCanceller):
    def process(self, near: bytes, far: bytes) -> bytes:
        del far
        return near

    @property
    def name(self) -> str:
        return "off"


class WebRtcEchoCanceller(EchoCanceller):
    def __init__(self, delay_ms: int) -> None:
        from webrtc_audio_processing import AudioProcessingModule  # type: ignore

        self._apm = AudioProcessingModule(
            enable_aec=True,
            enable_ns=True,
            enable_agc=False,
        )
        if hasattr(self._apm, "set_stream_delay_ms"):
            self._apm.set_stream_delay_ms(delay_ms)
        self._delay_ms = delay_ms

    def process(self, near: bytes, far: bytes) -> bytes:
        if far and hasattr(self._apm, "process_reverse_stream"):
            self._apm.process_reverse_stream(far)
        if hasattr(self._apm, "process_stream"):
            return bytes(self._apm.process_stream(near))
        return near

    @property
    def name(self) -> str:
        return f"webrtc(delay={self._delay_ms}ms)"


def build_echo_canceller() -> EchoCanceller:
    backend = os.getenv("AEC_BACKEND", "webrtc").strip().lower() or "webrtc"
    delay_ms = int(os.getenv("AEC_STREAM_DELAY_MS", "80"))
    if backend in {"off", "none", "passthrough"}:
        LOGGER.info("AEC disabled (passthrough)")
        return PassthroughEchoCanceller()
    try:
        canceller = WebRtcEchoCanceller(delay_ms)
    except Exception as exc:  # ImportError or native init failure
        LOGGER.warning("WebRTC AEC unavailable (%s); using passthrough", exc)
        return PassthroughEchoCanceller()
    LOGGER.info("AEC backend: %s", canceller.name)
    return canceller
