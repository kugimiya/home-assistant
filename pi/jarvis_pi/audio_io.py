"""Capture and playback via ALSA CLI tools."""

from __future__ import annotations

import subprocess
import threading
from typing import IO


class PcmCapture:
    def __init__(self, device: str, sample_rate: int) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self, sink: IO[bytes]) -> None:
        if self._process:
            return
        self._stop.clear()
        self._process = subprocess.Popen(
            [
                "arecord",
                "-D",
                self._device,
                "-f",
                "S16_LE",
                "-r",
                str(self._sample_rate),
                "-c",
                "1",
                "-t",
                "raw",
                "-B",
                "40000",
                "-F",
                "20000",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._thread = threading.Thread(target=self._pump, args=(sink,), daemon=True)
        self._thread.start()

    def _pump(self, sink: IO[bytes]) -> None:
        assert self._process and self._process.stdout
        while not self._stop.is_set():
            chunk = self._process.stdout.read(3200)
            if not chunk:
                break
            sink.write(chunk)

    def stop(self) -> None:
        self._stop.set()
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None


def play_pcm(device: str, pcm_data: bytes, sample_rate: int) -> None:
    subprocess.run(
        [
            "aplay",
            "-q",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-r",
            str(sample_rate),
            "-c",
            "1",
            "-t",
            "raw",
        ],
        input=pcm_data,
        check=True,
    )
