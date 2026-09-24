"""TCP client for Windows PCM uplink and control channel."""

from __future__ import annotations

import queue
import socket
import threading
import uuid
from typing import Callable

from jarvis_pi.protocol import AudioHeader, decode_message, encode_message

MessageCallback = Callable[[dict], None]


class WindowsClient:
    def __init__(self, host: str, pcm_port: int, control_port: int) -> None:
        self._host = host
        self._pcm_port = pcm_port
        self._control_port = control_port
        self._pcm_socket: socket.socket | None = None
        self._control_socket: socket.socket | None = None
        self._uplink_enabled = threading.Event()
        self._uplink_enabled.set()
        self._control_buffer = bytearray()
        self._control_lock = threading.Lock()
        self._pending_audio: dict[str, queue.Queue[tuple[bytes, int]]] = {}
        self._on_message: MessageCallback | None = None
        self._reader_thread: threading.Thread | None = None
        self._reader_stop = threading.Event()

    @property
    def uplink_enabled(self) -> threading.Event:
        return self._uplink_enabled

    def connect(self) -> None:
        self._control_socket = socket.create_connection((self._host, self._control_port))
        self._control_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._pcm_socket = socket.create_connection((self._host, self._pcm_port))
        self._pcm_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def start_control_reader(self, on_message: MessageCallback) -> None:
        self._on_message = on_message
        self._reader_stop.clear()
        self._reader_thread = threading.Thread(target=self._control_reader_loop, daemon=True)
        self._reader_thread.start()

    def pcm_write_sink(self) -> _PcmWriteSink:
        if not self._pcm_socket:
            raise RuntimeError("PCM socket is not connected")
        return _PcmWriteSink(self._pcm_socket, self._uplink_enabled)

    def request_speak(self, text: str, timeout_sec: float = 120.0) -> tuple[bytes, int]:
        if not self._control_socket:
            raise RuntimeError("Control socket is not connected")

        request_id = uuid.uuid4().hex
        response_queue: queue.Queue[tuple[bytes, int]] = queue.Queue(maxsize=1)
        with self._control_lock:
            self._pending_audio[request_id] = response_queue

        message = encode_message({"type": "speak", "id": request_id, "text": text})
        with self._control_lock:
            self._control_socket.sendall(message)

        try:
            return response_queue.get(timeout=timeout_sec)
        finally:
            with self._control_lock:
                self._pending_audio.pop(request_id, None)

    def _control_reader_loop(self) -> None:
        assert self._control_socket
        sock = self._control_socket
        while not self._reader_stop.is_set():
            try:
                message = self._read_message(sock)
            except (ConnectionError, OSError):
                break

            msg_type = message.get("type")
            if msg_type == "audio":
                request_id = str(message.get("id", ""))
                header = AudioHeader.from_dict(message)
                audio = self._read_exact(sock, header.nbytes)
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
        for sock in (self._pcm_socket, self._control_socket):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        self._pcm_socket = None
        self._control_socket = None
        if self._reader_thread:
            self._reader_thread.join(timeout=2)
            self._reader_thread = None


class _PcmWriteSink:
    def __init__(self, sock: socket.socket, enabled: threading.Event) -> None:
        self._sock = sock
        self._enabled = enabled

    def write(self, data: bytes) -> int:
        if not data:
            return 0
        if self._enabled.is_set():
            self._sock.sendall(data)
        return len(data)

    def flush(self) -> None:
        return
