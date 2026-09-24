"""TCP servers for PCM uplink and control channel."""

from __future__ import annotations

import logging
import socket
import threading

from jarvis_win.config import WindowsConfig
from jarvis_win.protocol import decode_message, encode_message
from jarvis_win.stt_vosk import StreamingRecognizer
from jarvis_win.tts_piper import synthesize_pcm

LOGGER = logging.getLogger("jarvis_win.server")


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

    def read_json_line(self) -> dict:
        while True:
            if b"\n" in self._buffer:
                line, rest = self._buffer.split(b"\n", 1)
                self._buffer = bytearray(rest)
                return decode_message(line)
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Control channel closed")
            self._buffer.extend(chunk)


class AudioService:
    def __init__(self, config: WindowsConfig) -> None:
        self._config = config
        self._control: ControlChannel | None = None
        self._control_lock = threading.Lock()

    def run(self) -> None:
        control_thread = threading.Thread(target=self._serve_control, daemon=True)
        pcm_thread = threading.Thread(target=self._serve_pcm, daemon=True)
        control_thread.start()
        pcm_thread.start()
        control_thread.join()
        pcm_thread.join()

    def _serve_control(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self._config.control_listen_host, self._config.control_listen_port))
            server.listen(1)
            LOGGER.info("Control listening on %s:%s", self._config.control_listen_host, self._config.control_listen_port)
            conn, addr = server.accept()
            LOGGER.info("Control connected from %s", addr[0])
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            channel = ControlChannel(conn)
            with self._control_lock:
                self._control = channel
            try:
                self._handle_control(channel)
            finally:
                with self._control_lock:
                    self._control = None
                conn.close()

    def _handle_control(self, channel: ControlChannel) -> None:
        while True:
            message = channel.read_json_line()
            if message.get("type") != "speak":
                continue
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

    def _serve_pcm(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self._config.pcm_listen_host, self._config.pcm_listen_port))
            server.listen(1)
            LOGGER.info("PCM listening on %s:%s", self._config.pcm_listen_host, self._config.pcm_listen_port)
            conn, addr = server.accept()
            LOGGER.info("PCM connected from %s", addr[0])
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            recognizer = StreamingRecognizer(str(self._config.vosk_model_path), self._config.sample_rate)
            try:
                while True:
                    chunk = conn.recv(3200)
                    if not chunk:
                        break
                    for text, is_final in recognizer.feed(chunk):
                        self._emit_stt(text, is_final)
            finally:
                conn.close()

    def _emit_stt(self, text: str, is_final: bool) -> None:
        with self._control_lock:
            control = self._control
        if not control:
            return
        payload = {"type": "final" if is_final else "partial", "text": text}
        control.send_json(payload)
