"""TCP client for Windows PCM uplink and control channel."""

from __future__ import annotations

import logging
import queue
import socket
import threading
import time
import uuid
from typing import Callable

from jarvis_pi.protocol import AudioHeader, decode_message, encode_message

LOGGER = logging.getLogger("jarvis_pi.windows_client")

MessageCallback = Callable[[dict], None]

_RECONNECT_INITIAL_DELAY_SEC = 2.0
_RECONNECT_MAX_DELAY_SEC = 30.0
_RECONNECT_MAX_ATTEMPTS = 15


class WindowsClient:
    def __init__(self, host: str, pcm_port: int, control_port: int) -> None:
        self._host = host
        self._pcm_port = pcm_port
        self._control_port = control_port
        self._pcm_socket: socket.socket | None = None
        self._control_socket: socket.socket | None = None
        self._conn_lock = threading.RLock()
        self._uplink_enabled = threading.Event()
        self._uplink_enabled.set()
        self._control_buffer = bytearray()
        self._control_lock = threading.Lock()
        self._pending_audio: dict[str, queue.Queue[tuple[bytes, int]]] = {}
        self._on_message: MessageCallback | None = None
        self._reader_thread: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._pcm_sink: _PcmWriteSink | None = None

    @property
    def uplink_enabled(self) -> threading.Event:
        return self._uplink_enabled

    def connect(self) -> None:
        with self._conn_lock:
            self._open_sockets()

    def reconnect(self, *, reason: str = "") -> bool:
        if self._reader_stop.is_set():
            return False
        if reason:
            LOGGER.warning(
                "Windows link lost (%s), reconnecting to %s...",
                reason,
                self._host,
            )
        else:
            LOGGER.warning("Reconnecting to Windows %s...", self._host)

        delay = _RECONNECT_INITIAL_DELAY_SEC
        for attempt in range(1, _RECONNECT_MAX_ATTEMPTS + 1):
            if self._reader_stop.is_set():
                return False
            with self._conn_lock:
                self._close_sockets()
                try:
                    self._open_sockets()
                except OSError as exc:
                    LOGGER.warning(
                        "Reconnect attempt %d/%d failed: %s",
                        attempt,
                        _RECONNECT_MAX_ATTEMPTS,
                        exc,
                    )
                else:
                    if self._pcm_sink is not None:
                        self._pcm_sink.set_socket(self._pcm_socket)
                    LOGGER.info("Reconnected to Windows %s", self._host)
                    return True
            time.sleep(delay)
            delay = min(delay * 1.5, _RECONNECT_MAX_DELAY_SEC)

        LOGGER.error("Could not reconnect to Windows %s after %d attempts", self._host, _RECONNECT_MAX_ATTEMPTS)
        return False

    def _open_sockets(self) -> None:
        # create_connection(timeout=...) leaves that timeout on the socket.
        # Control reads are often idle for long stretches (no STT), so clear it
        # after connect — otherwise recv raises socket.timeout every N seconds
        # and the reader treats it as a dead link.
        self._control_socket = socket.create_connection(
            (self._host, self._control_port), timeout=10.0
        )
        self._control_socket.settimeout(None)
        self._control_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._control_socket.sendall(encode_message({"type": "hello", "role": "pi"}))
        self._pcm_socket = socket.create_connection(
            (self._host, self._pcm_port), timeout=10.0
        )
        self._pcm_socket.settimeout(None)
        self._pcm_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def _close_sockets(self) -> None:
        for sock in (self._pcm_socket, self._control_socket):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        self._pcm_socket = None
        self._control_socket = None
        self._control_buffer.clear()

    def _send_pcm(self, data: bytes) -> None:
        with self._conn_lock:
            if not self._pcm_socket:
                raise OSError("PCM socket is not connected")
            self._pcm_socket.sendall(data)

    def _send_control(self, payload: bytes) -> None:
        with self._conn_lock:
            if not self._control_socket:
                raise OSError("Control socket is not connected")
            self._control_socket.sendall(payload)

    def start_control_reader(self, on_message: MessageCallback) -> None:
        self._on_message = on_message
        self._reader_stop.clear()
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._reader_thread = threading.Thread(target=self._control_reader_loop, daemon=True)
        self._reader_thread.start()

    def pcm_write_sink(self) -> _PcmWriteSink:
        if not self._pcm_socket:
            raise RuntimeError("PCM socket is not connected")
        if self._pcm_sink is None:
            self._pcm_sink = _PcmWriteSink(self)
        else:
            self._pcm_sink.set_socket(self._pcm_socket)
        return self._pcm_sink

    def send_stt_reset(self) -> None:
        message = encode_message({"type": "stt_reset"})
        try:
            self._send_control(message)
        except OSError:
            if self.reconnect(reason="stt_reset"):
                self._send_control(message)

    def request_speak(self, text: str, timeout_sec: float = 120.0) -> tuple[bytes, int]:
        if not self._control_socket:
            if not self.reconnect(reason="request_speak"):
                raise RuntimeError("Control socket is not connected")

        request_id = uuid.uuid4().hex
        response_queue: queue.Queue[tuple[bytes, int]] = queue.Queue(maxsize=1)
        with self._control_lock:
            self._pending_audio[request_id] = response_queue

        message = encode_message({"type": "speak", "id": request_id, "text": text})
        try:
            self._send_control(message)
        except OSError:
            if not self.reconnect(reason="request_speak send"):
                with self._control_lock:
                    self._pending_audio.pop(request_id, None)
                raise
            self._send_control(message)

        try:
            return response_queue.get(timeout=timeout_sec)
        finally:
            with self._control_lock:
                self._pending_audio.pop(request_id, None)

    def _control_reader_loop(self) -> None:
        while not self._reader_stop.is_set():
            sock = self._control_socket
            if not sock:
                if not self.reconnect(reason="control reader idle"):
                    time.sleep(_RECONNECT_INITIAL_DELAY_SEC)
                continue
            try:
                message = self._read_message(sock)
            except socket.timeout:
                # Idle control channel is normal; do not reconnect.
                continue
            except (ConnectionError, OSError):
                if self._reader_stop.is_set():
                    break
                self.reconnect(reason="control read")
                continue

            msg_type = message.get("type")
            if msg_type == "audio":
                request_id = str(message.get("id", ""))
                header = AudioHeader.from_dict(message)
                try:
                    audio = self._read_exact(sock, header.nbytes)
                except (ConnectionError, OSError):
                    if self._reader_stop.is_set():
                        break
                    self.reconnect(reason="control audio read")
                    continue
                pending = self._pending_audio.get(request_id)
                if pending:
                    pending.put((audio, header.sample_rate))
                continue

            if self._on_message:
                self._on_message(message)

    def _read_message(self, sock: socket.socket) -> dict:
        line = self._read_line(sock)
        return decode_message(line)

    def _read_line(self, sock: socket.socket) -> bytes:
        while True:
            if b"\n" in self._control_buffer:
                line, rest = self._control_buffer.split(b"\n", 1)
                self._control_buffer = bytearray(rest)
                return line
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("Control channel closed")
            self._control_buffer.extend(chunk)

    def _read_exact(self, sock: socket.socket, nbytes: int) -> bytes:
        while len(self._control_buffer) < nbytes:
            chunk = sock.recv(max(4096, nbytes - len(self._control_buffer)))
            if not chunk:
                raise ConnectionError("Control channel closed while reading audio")
            self._control_buffer.extend(chunk)
        data = bytes(self._control_buffer[:nbytes])
        del self._control_buffer[:nbytes]
        return data

    def close(self) -> None:
        self._reader_stop.set()
        with self._conn_lock:
            self._close_sockets()
        if self._reader_thread:
            self._reader_thread.join(timeout=2)
            self._reader_thread = None


class _PcmWriteSink:
    def __init__(self, client: WindowsClient) -> None:
        self._client = client
        self._sock = client._pcm_socket
        self._enabled = client._uplink_enabled

    def set_socket(self, sock: socket.socket | None) -> None:
        self._sock = sock

    def write(self, data: bytes) -> int:
        if not data:
            return 0
        if not self._enabled.is_set():
            return len(data)
        try:
            self._client._send_pcm(data)
        except OSError:
            if self._client.reconnect(reason="pcm uplink"):
                self._client._send_pcm(data)
            else:
                LOGGER.debug("Dropping PCM chunk after failed reconnect (%d bytes)", len(data))
        return len(data)

    def flush(self) -> None:
        return
