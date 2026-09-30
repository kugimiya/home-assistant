"""TCP servers for PCM uplink and control channel."""

from __future__ import annotations

import logging
import os
import select
import socket
import sys
import threading
from typing import Protocol

from jarvis_win.config import WindowsConfig
from jarvis_win.protocol import decode_message, encode_message
from jarvis_win.tts_piper import synthesize_pcm

LOGGER = logging.getLogger("jarvis_win.server")

# Dead Pi links often never send FIN (Wi-Fi drop, kill -9 on the far side of NAT).
# Keepalive lets recv/select notice that, instead of spinning on an uplink gap forever.
_KEEPALIVE_IDLE_SEC = 10.0
_KEEPALIVE_INTERVAL_SEC = 2.0
_KEEPALIVE_COUNT = 3


class _StreamingRecognizer(Protocol):
    def feed(self, chunk: bytes) -> list[tuple[str, bool]]: ...


class _RecognizerFactory(Protocol):
    def create_recognizer(self) -> _StreamingRecognizer: ...


class ControlChannel:
    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._send_lock = threading.Lock()
        self._buffer = bytearray()

    def send_json(self, payload: dict) -> None:
        with self._send_lock:
            self._sock.sendall(encode_message(payload))

    def send_audio(self, request_id: str, sample_rate: int, audio: bytes) -> None:
        header = {
            "type": "audio",
            "id": request_id,
            "sample_rate": sample_rate,
            "nbytes": len(audio),
        }
        with self._send_lock:
            self._sock.sendall(encode_message(header))
            if audio:
                self._sock.sendall(audio)

    def read_json_line(self) -> dict | None:
        while True:
            if b"\n" in self._buffer:
                line, rest = self._buffer.split(b"\n", 1)
                self._buffer = bytearray(rest)
                return decode_message(line)
            chunk = self._sock.recv(4096)
            if not chunk:
                return None
            self._buffer.extend(chunk)

    def has_complete_line(self) -> bool:
        return b"\n" in self._buffer


def _close_socket(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _enable_tcp_keepalive(sock: socket.socket) -> None:
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if sys.platform == "win32" and hasattr(socket, "SIO_KEEPALIVE_VALS"):
            sock.ioctl(
                socket.SIO_KEEPALIVE_VALS,
                (1, int(_KEEPALIVE_IDLE_SEC * 1000), int(_KEEPALIVE_INTERVAL_SEC * 1000)),
            )
            return
        if hasattr(socket, "TCP_KEEPIDLE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, int(_KEEPALIVE_IDLE_SEC))
        if hasattr(socket, "TCP_KEEPINTVL"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, int(_KEEPALIVE_INTERVAL_SEC))
        if hasattr(socket, "TCP_KEEPCNT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _KEEPALIVE_COUNT)
    except OSError:
        LOGGER.warning("TCP keepalive not enabled", exc_info=True)


def _prepare_client_socket(sock: socket.socket) -> None:
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(None)
    _enable_tcp_keepalive(sock)


def _select_readable(sockets: list[socket.socket], timeout: float | None) -> list[socket.socket]:
    while True:
        try:
            readable, _, _ = select.select(sockets, [], [], timeout)
            return list(readable)
        except InterruptedError:
            continue


class _PcmSession:
    def __init__(self, vosk: _RecognizerFactory) -> None:
        self._vosk = vosk
        self._lock = threading.Lock()
        self._recognizer = vosk.create_recognizer()

    def reset(self) -> None:
        with self._lock:
            self._recognizer = self._vosk.create_recognizer()

    def feed(self, chunk: bytes):
        with self._lock:
            return self._recognizer.feed(chunk)


class AudioService:
    def __init__(self, config: WindowsConfig, vosk: _RecognizerFactory | None = None) -> None:
        self._config = config
        self._control: ControlChannel | None = None
        self._control_lock = threading.Lock()
        self._pcm_session: _PcmSession | None = None
        self._pcm_session_lock = threading.Lock()
        if vosk is None:
            LOGGER.info("Loading Vosk model from %s", config.vosk_model_path)
            from jarvis_win.stt_vosk import VoskEngine

            self._vosk: _RecognizerFactory = VoskEngine(
                str(config.vosk_model_path),
                config.sample_rate,
            )
            LOGGER.info("Vosk model loaded")
        else:
            self._vosk = vosk

    def _reset_stt(self, reason: str) -> None:
        with self._pcm_session_lock:
            session = self._pcm_session
        if session:
            session.reset()
            LOGGER.info("STT recognizer reset (%s)", reason)

    def run(self) -> None:
        control_thread = threading.Thread(target=self._serve_control, daemon=True)
        pcm_thread = threading.Thread(target=self._serve_pcm, daemon=True)
        control_thread.start()
        pcm_thread.start()
        control_thread.join()
        pcm_thread.join()

    def _serve_control(self) -> None:
        server = self._listen_socket(self._config.control_listen_host, self._config.control_listen_port)
        LOGGER.info("Control listening on %s:%s", self._config.control_listen_host, self._config.control_listen_port)
        conn: socket.socket | None = None
        channel: ControlChannel | None = None
        try:
            while True:
                if conn is None or channel is None:
                    try:
                        conn, addr = server.accept()
                    except OSError as exc:
                        if server.fileno() == -1:
                            raise
                        LOGGER.warning("Control accept failed: %s", exc)
                        conn = None
                        channel = None
                        continue
                    LOGGER.info("Control connected from %s", addr[0])
                    _prepare_client_socket(conn)
                    channel = ControlChannel(conn)
                    with self._control_lock:
                        self._control = channel

                # A line already buffered must not wait for the next socket event,
                # or the second message in one recv sits unread until more bytes arrive.
                if channel.has_complete_line():
                    if not self._take_control_message(conn, channel):
                        conn = None
                        channel = None
                    continue

                # Watch the listener together with the client. A reconnected Pi
                # completes the TCP handshake into the backlog while the previous
                # socket is still half-open; accept() has to run or that client
                # is never read.
                readable = _select_readable([conn, server], None)
                if server in readable:
                    LOGGER.info("Control client replaced by a new connection")
                    self._detach_control(conn)
                    conn = None
                    channel = None
                    continue
                if not readable:
                    continue
                if not self._take_control_message(conn, channel):
                    conn = None
                    channel = None
        finally:
            if conn is not None:
                self._detach_control(conn)
            server.close()

    def _take_control_message(self, conn: socket.socket, channel: ControlChannel) -> bool:
        try:
            message = channel.read_json_line()
        except (ConnectionError, OSError) as exc:
            LOGGER.info("Control client disconnected: %s", exc)
            self._detach_control(conn)
            return False
        if message is None:
            LOGGER.info("Control client disconnected")
            self._detach_control(conn)
            return False
        if not self._dispatch_control(channel, message):
            self._detach_control(conn)
            return False
        return True

    def _detach_control(self, conn: socket.socket) -> None:
        with self._control_lock:
            self._control = None
        _close_socket(conn)

    def _dispatch_control(self, channel: ControlChannel, message: dict) -> bool:
        """Handle one control message. Return False when the socket is dead."""
        try:
            msg_type = message.get("type")
            if msg_type == "hello":
                channel.send_json({"type": "ready"})
                return True
            if msg_type == "stt_reset":
                self._reset_stt("pi request")
                return True
            if msg_type != "speak":
                return True

            request_id = str(message.get("id", ""))
            text = str(message.get("text", ""))
            LOGGER.info("Synthesize request %s (%d chars)", request_id, len(text))
            audio, sample_rate = synthesize_pcm(
                text,
                self._config.piper_bin,
                self._config.piper_model,
                self._config.piper_config,
            )
            channel.send_audio(request_id, sample_rate, audio)
            return True
        except (ConnectionError, OSError) as exc:
            LOGGER.info("Control client disconnected: %s", exc)
            return False

    def _serve_pcm(self) -> None:
        server = self._listen_socket(self._config.pcm_listen_host, self._config.pcm_listen_port)
        LOGGER.info("PCM listening on %s:%s", self._config.pcm_listen_host, self._config.pcm_listen_port)
        conn: socket.socket | None = None
        session: _PcmSession | None = None
        try:
            while True:
                if conn is None or session is None:
                    try:
                        conn, addr = server.accept()
                    except OSError as exc:
                        if server.fileno() == -1:
                            raise
                        LOGGER.warning("PCM accept failed: %s", exc)
                        conn = None
                        session = None
                        continue
                    LOGGER.info("PCM connected from %s", addr[0])
                    _prepare_client_socket(conn)
                    session = _PcmSession(self._vosk)
                    with self._pcm_session_lock:
                        self._pcm_session = session

                uplink_gap_sec = float(os.getenv("PCM_UPLINK_GAP_RESET_SEC", "1.0"))
                readable = _select_readable([conn, server], uplink_gap_sec)
                if server in readable:
                    LOGGER.info("PCM client replaced by a new connection")
                    self._detach_pcm(conn, session)
                    conn = None
                    session = None
                    continue
                if not readable:
                    session.reset()
                    LOGGER.info(
                        "STT recognizer reset (uplink gap > %.2fs)",
                        uplink_gap_sec,
                    )
                    continue
                try:
                    chunk = conn.recv(3200)
                except OSError as exc:
                    LOGGER.info("PCM client disconnected: %s", exc)
                    self._detach_pcm(conn, session)
                    conn = None
                    session = None
                    continue
                if not chunk:
                    LOGGER.info("PCM client disconnected")
                    self._detach_pcm(conn, session)
                    conn = None
                    session = None
                    continue
                for text, is_final in session.feed(chunk):
                    self._emit_stt(text, is_final)
        finally:
            if conn is not None and session is not None:
                self._detach_pcm(conn, session)
            server.close()

    def _detach_pcm(self, conn: socket.socket, session: _PcmSession) -> None:
        with self._pcm_session_lock:
            if self._pcm_session is session:
                self._pcm_session = None
        _close_socket(conn)

    @staticmethod
    def _listen_socket(host: str, port: int) -> socket.socket:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(5)
        return server

    def _emit_stt(self, text: str, is_final: bool) -> None:
        with self._control_lock:
            control = self._control
        if not control:
            return
        payload = {"type": "final" if is_final else "partial", "text": text}
        try:
            control.send_json(payload)
        except OSError as exc:
            LOGGER.warning("Failed to send STT event: %s", exc)
