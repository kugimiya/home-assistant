"""STT/TTS module lifecycle and health snapshots."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from jarvis_win.config import WindowsConfig
from jarvis_win.tts_piper import default_synth_timeout_sec, synthesize_pcm

LOGGER = logging.getLogger("jarvis_win.audio_modules")

ModuleStateName = Literal["unloaded", "loading", "ready", "error"]


class _RecognizerFactory(Protocol):
    def create_recognizer(self): ...


@dataclass
class ModuleSnapshot:
    state: ModuleStateName
    error: str | None
    paths_ok: bool | None = None

    def to_dict(self) -> dict:
        payload: dict = {"state": self.state, "error": self.error}
        if self.paths_ok is not None:
            payload["paths_ok"] = self.paths_ok
        return payload


class AudioModules:
    """Thread-safe STT/TTS load state; models load on demand via reload/load."""

    def __init__(
        self,
        config: WindowsConfig,
        *,
        stt_factory: _RecognizerFactory | None = None,
    ) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._stt_inject = stt_factory
        self._stt_engine: _RecognizerFactory | None = None
        self._stt_state: ModuleStateName = "ready" if stt_factory is not None else "unloaded"
        self._stt_error: str | None = None
        if stt_factory is not None:
            self._stt_engine = stt_factory

        self._tts_state: ModuleStateName = "unloaded"
        self._tts_error: str | None = None
        self._tts_paths_ok = self._check_tts_paths()

    def _check_tts_paths(self) -> bool:
        cfg = self._config
        return cfg.piper_bin.is_file() and cfg.piper_model.is_file()

    def stt_ready(self) -> bool:
        with self._lock:
            return self._stt_state == "ready" and self._stt_engine is not None

    def tts_ready(self) -> bool:
        with self._lock:
            return self._tts_state == "ready"

    def get_stt_factory(self) -> _RecognizerFactory | None:
        with self._lock:
            return self._stt_engine

    def snapshot_stt(self) -> ModuleSnapshot:
        with self._lock:
            return ModuleSnapshot(state=self._stt_state, error=self._stt_error)

    def snapshot_tts(self) -> ModuleSnapshot:
        with self._lock:
            return ModuleSnapshot(
                state=self._tts_state,
                error=self._tts_error,
                paths_ok=self._tts_paths_ok,
            )

    def health_payload(self, request_id: str) -> dict:
        stt = self.snapshot_stt()
        tts = self.snapshot_tts()
        ok = stt.state == "ready" and tts.state == "ready"
        return {
            "type": "health",
            "id": request_id,
            "ok": ok,
            "stt": stt.to_dict(),
            "tts": tts.to_dict(),
        }

    def mark_stt_error(self, message: str) -> None:
        with self._lock:
            self._stt_state = "error"
            self._stt_error = message
        LOGGER.error("STT module error: %s", message)

    def mark_tts_error(self, message: str) -> None:
        with self._lock:
            self._tts_state = "error"
            self._tts_error = message
        LOGGER.error("TTS module error: %s", message)

    def load_stt(self) -> ModuleSnapshot:
        with self._lock:
            self._stt_state = "loading"
            self._stt_error = None
        try:
            if self._stt_inject is not None:
                engine = self._stt_inject
            else:
                LOGGER.info("Loading Vosk model from %s", self._config.vosk_model_path)
                from jarvis_win.stt_vosk import VoskEngine

                engine = VoskEngine(
                    str(self._config.vosk_model_path),
                    self._config.sample_rate,
                )
                LOGGER.info("Vosk model loaded")
            with self._lock:
                self._stt_engine = engine
                self._stt_state = "ready"
                self._stt_error = None
        except Exception as exc:
            with self._lock:
                self._stt_engine = None
                self._stt_state = "error"
                self._stt_error = str(exc)
            LOGGER.exception("STT load failed")
        return self.snapshot_stt()

    def load_tts(self) -> ModuleSnapshot:
        with self._lock:
            self._tts_state = "loading"
            self._tts_error = None
            self._tts_paths_ok = self._check_tts_paths()
        if not self._tts_paths_ok:
            msg = "Piper binary or model missing"
            with self._lock:
                self._tts_state = "error"
                self._tts_error = msg
            return self.snapshot_tts()

        probe_timeout = float(os.getenv("PIPER_PROBE_TIMEOUT_SEC", "30"))
        probe_text = os.getenv("PIPER_PROBE_TEXT", ".")
        try:
            synthesize_pcm(
                probe_text,
                self._config.piper_bin,
                self._config.piper_model,
                self._config.piper_config,
                timeout=probe_timeout,
            )
            with self._lock:
                self._tts_state = "ready"
                self._tts_error = None
        except Exception as exc:
            with self._lock:
                self._tts_state = "error"
                self._tts_error = str(exc)
            LOGGER.exception("TTS probe failed")
        return self.snapshot_tts()

    def reload(
        self,
        modules: list[str],
        *,
        on_stt_reloaded: Callable[[], None] | None = None,
    ) -> dict:
        targets = {m.strip().lower() for m in modules if m.strip()}
        if "all" in targets:
            targets = {"stt", "tts"}

        stt_snap = self.snapshot_stt()
        tts_snap = self.snapshot_tts()

        if "stt" in targets:
            with self._lock:
                self._stt_engine = None
                if self._stt_inject is None:
                    self._stt_state = "unloaded"
            stt_snap = self.load_stt()
            if on_stt_reloaded is not None:
                on_stt_reloaded()

        if "tts" in targets:
            with self._lock:
                self._tts_state = "unloaded"
            tts_snap = self.load_tts()

        return {"stt": stt_snap.to_dict(), "tts": tts_snap.to_dict()}
