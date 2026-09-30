"""A half-open Pi socket must not block the next connection."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import types
import unittest
from pathlib import Path

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
        self.fed = bytearray()
        self.creates = 0
        self._lock = threading.Lock()

    def create_recognizer(self) -> _FakeVosk:
        with self._lock:
            self.creates += 1
        return self

    def feed(self, chunk: bytes) -> list[tuple[str, bool]]:
        with self._lock:
            self.fed.extend(chunk)
        if b"WAKE" in chunk:
            return [("привет", True)]
        return []

    def fed_bytes(self) -> bytes:
        with self._lock:
            return bytes(self.fed)


def _wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met")


class ReconnectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._sockets: list[socket.socket] = []
        self.vosk = _FakeVosk()
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
        self.pcm_port = pcm_port
        self.control_port = control_port
        self.service = AudioService(config, vosk=self.vosk)
        self._errors: list[BaseException] = []

        def run() -> None:
            try:
                self.service.run()
            except BaseException as exc:
                self._errors.append(exc)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        for sock in self._sockets:
            try:
                sock.close()
            except OSError:
                pass

    def _hold(self, port: int) -> socket.socket:
        sock = _connect(port)
        self._sockets.append(sock)
        return sock

    def test_new_client_replaces_half_open_session(self) -> None:
        stale_control = self._hold(self.control_port)
        stale_pcm = self._hold(self.pcm_port)
        self.assertIsNotNone(stale_control)
        self.assertIsNotNone(stale_pcm)

        control = self._hold(self.control_port)
        control.sendall(encode_message({"type": "hello", "role": "pi"}))
        ready = _recv_json(control)
        self.assertEqual(ready.get("type"), "ready")

        pcm = self._hold(self.pcm_port)
        pcm.sendall(b"xxWAKEyy")
        event = _recv_json(control)
        self.assertEqual(event, {"type": "final", "text": "привет"})
        self.assertIn(b"WAKE", self.vosk.fed_bytes())
        self.assertFalse(self._errors)

    def test_same_socket_survives_uplink_gap(self) -> None:
        import os

        os.environ["PCM_UPLINK_GAP_RESET_SEC"] = "0.2"
        pcm = self._hold(self.pcm_port)
        pcm.sendall(b"AAAA")
        _wait_until(lambda: b"AAAA" in self.vosk.fed_bytes())
        created = self.vosk.creates
        _wait_until(lambda: self.vosk.creates > created, timeout=2.0)
        pcm.sendall(b"BBBB")
        _wait_until(lambda: b"BBBB" in self.vosk.fed_bytes())
        self.assertFalse(self._errors)


if __name__ == "__main__":
    unittest.main()
