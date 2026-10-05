"""Health/reload control messages and non-blocking speak."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

if "dotenv" not in sys.modules:
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: False  # type: ignore[attr-defined]
    sys.modules["dotenv"] = dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis_win.config import WindowsConfig
from jarvis_win.protocol import encode_message
from jarvis_win.server import AudioService


def _free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _connect(port: int, timeout: float = 3.0) -> socket.socket:
    deadline = time.monotonic() + timeout
    last: OSError | None = None
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=0.5)
        except OSError as exc:
            last = exc
            time.sleep(0.02)
    raise AssertionError(f"could not connect to port {port}: {last}")


def _recv_json(sock: socket.socket, timeout: float = 3.0) -> dict:
    sock.settimeout(timeout)
    buf = bytearray()
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf.extend(chunk)
    line = bytes(buf).split(b"\n", 1)[0]
    return json.loads(line.decode("utf-8"))


class _FakeVosk:
    def __init__(self) -> None:
        self.creates = 0
        self._lock = threading.Lock()

    def create_recognizer(self) -> _FakeVosk:
        with self._lock:
            self.creates += 1
        return self

    def feed(self, chunk: bytes) -> list[tuple[str, bool]]:
        if b"WAKE" in chunk:
            return [("привет", True)]
        return []


def _service_config() -> tuple[WindowsConfig, int, int]:
    pcm_port = _free_port()
    control_port = _free_port()
    config = WindowsConfig(
        pcm_listen_host="127.0.0.1",
        pcm_listen_port=pcm_port,
        control_listen_host="127.0.0.1",
        control_listen_port=control_port,
        vosk_model_path=Path("."),
        piper_bin=Path("."),
        piper_model=Path("."),
        piper_config=Path("."),
        sample_rate=16000,
    )
    return config, pcm_port, control_port


class HealthReloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._sockets: list[socket.socket] = []
        self._errors: list[BaseException] = []

    def tearDown(self) -> None:
        for sock in self._sockets:
            try:
                sock.close()
            except OSError:
                pass

    def _start_service(self, service: AudioService) -> threading.Thread:
        def run() -> None:
            try:
                service.run()
            except BaseException as exc:
                self._errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def _control(self, port: int) -> socket.socket:
        sock = _connect(port)
        self._sockets.append(sock)
        return sock

    def test_health_reports_lazy_modules(self) -> None:
        config, _, control_port = _service_config()
        service = AudioService(config)
        self._start_service(service)

        control = self._control(control_port)
        control.sendall(encode_message({"type": "health", "id": "h1"}))
        health = _recv_json(control)
        self.assertEqual(health.get("type"), "health")
        self.assertEqual(health.get("id"), "h1")
        self.assertFalse(health.get("ok"))
        self.assertEqual(health.get("stt", {}).get("state"), "unloaded")
        self.assertFalse(self._errors)

    def test_reload_stt_enables_pcm(self) -> None:
        config, pcm_port, control_port = _service_config()
        vosk = _FakeVosk()
        service = AudioService(config, vosk=vosk)
        self._start_service(service)

        control = self._control(control_port)
        control.sendall(
            encode_message({"type": "reload_modules", "id": "r1", "modules": ["stt"]})
        )
        reload = _recv_json(control)
        self.assertEqual(reload.get("stt", {}).get("state"), "ready")

        pcm = self._control(pcm_port)
        pcm.sendall(b"xxWAKEyy")
        event = _recv_json(control)
        self.assertEqual(event, {"type": "final", "text": "привет"})
        self.assertGreaterEqual(vosk.creates, 1)
        self.assertFalse(self._errors)

    @patch("jarvis_win.server.synthesize_pcm")
    def test_health_while_speak_runs(self, mock_synth) -> None:
        config, _, control_port = _service_config()
        vosk = _FakeVosk()
        service = AudioService(config, vosk=vosk)
        with service._modules._lock:
            service._modules._tts_state = "ready"
        self._start_service(service)

        def slow_synth(*_args, **_kwargs):
            time.sleep(1.5)
            return b"\x00\x00", 22050

        mock_synth.side_effect = slow_synth

        control = self._control(control_port)
        control.sendall(encode_message({"type": "speak", "id": "s1", "text": "hi"}))

        time.sleep(0.2)
        control.sendall(encode_message({"type": "health", "id": "h2"}))
        health = _recv_json(control, timeout=2.0)
        self.assertEqual(health.get("type"), "health")
        self.assertEqual(health.get("id"), "h2")
        self.assertFalse(self._errors)


if __name__ == "__main__":
    unittest.main()
