"""Full-duplex capture/playback with a far-end reference for AEC."""

from __future__ import annotations

import logging
import queue
import subprocess
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

from jarvis_pi.aec import EchoCanceller, PassthroughEchoCanceller
from jarvis_pi.playback_timeline import PlaybackTimeline
from jarvis_pi.resample import resample_s16_mono

LOGGER = logging.getLogger("jarvis_pi.audio_engine")

SAMPLE_RATE = 16000
FRAME_SAMPLES = 160
FRAME_BYTES = FRAME_SAMPLES * 2


@dataclass
class _Item:
    pcm: bytes
    text: str | None
    done: threading.Event
    cancelled: bool = False


class AudioEngine:
    def __init__(
        self,
        *,
        input_device: str,
        output_device: str,
        canceller: EchoCanceller | None = None,
        uplink_write=None,
        on_clean_frame=None,
    ) -> None:
        self.input_device = input_device
        self.output_device = output_device
        self.canceller = canceller or PassthroughEchoCanceller()
        self.uplink_write = uplink_write
        self.on_clean_frame = on_clean_frame
        self.timeline = PlaybackTimeline()
        self._queue: queue.Queue[_Item | None] = queue.Queue()
        self._stop = threading.Event()
        self._interrupt = threading.Event()
        self._playing = threading.Event()
        self._play_thread: threading.Thread | None = None
        self._cap_thread: threading.Thread | None = None
        self._far_lock = threading.Lock()
        self._far = bytearray()
        self._delay_bytes = int(int(__import__("os").getenv("AEC_STREAM_DELAY_MS", "80")) * SAMPLE_RATE / 1000) * 2

    def start(self) -> None:
        self._stop.clear()
        self._play_thread = threading.Thread(target=self._playback_loop, name="audio-play", daemon=True)
        self._cap_thread = threading.Thread(target=self._capture_loop, name="audio-cap", daemon=True)
        self._play_thread.start()
        self._cap_thread.start()
        LOGGER.info("Audio engine started (AEC=%s)", self.canceller.name)

    def stop(self) -> None:
        self._stop.set()
        self._interrupt.set()
        self._queue.put(None)
        if self._play_thread:
            self._play_thread.join(timeout=2)
        if self._cap_thread:
            self._cap_thread.join(timeout=2)

    def is_playing(self) -> bool:
        return self._playing.is_set()

    def stop_playback(self) -> None:
        self._interrupt.set()
        pending: list[_Item] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            item.cancelled = True
            item.done.set()
            pending.append(item)
        del pending

    def play_pcm(self, pcm_16k: bytes, *, text: str | None = None) -> bool:
        """Play 16 kHz mono S16. Return False if interrupted."""
        item = _Item(pcm=pcm_16k, text=text, done=threading.Event())
        self._interrupt.clear()
        self._queue.put(item)
        item.done.wait()
        return not item.cancelled

    def play_wav(self, path: Path, *, text: str | None = None) -> bool:
        pcm, rate = _read_wav_pcm(path)
        if rate != SAMPLE_RATE:
            pcm = resample_s16_mono(pcm, rate, SAMPLE_RATE)
        return self.play_pcm(pcm, text=text)

    def _playback_loop(self) -> None:
        player = _Output(self.output_device)
        try:
            player.open()
            while not self._stop.is_set():
                item = self._queue.get()
                if item is None or self._stop.is_set():
                    break
                self._playing.set()
                self._play_item(player, item)
                self._playing.clear()
                item.done.set()
        finally:
            player.close()

    def _play_item(self, player: _Output, item: _Item) -> None:
        pcm = item.pcm
        duration = len(pcm) / (SAMPLE_RATE * 2)
        if item.text:
            self.timeline.note(item.text, duration)
        offset = 0
        while offset < len(pcm):
            if self._interrupt.is_set() or self._stop.is_set():
                item.cancelled = True
                return
            frame = pcm[offset : offset + FRAME_BYTES]
            if len(frame) < FRAME_BYTES:
                frame = frame + b"\x00" * (FRAME_BYTES - len(frame))
            player.write(frame)
            with self._far_lock:
                self._far.extend(frame)
                if len(self._far) > SAMPLE_RATE * 2 * 2:
                    del self._far[: len(self._far) - SAMPLE_RATE * 4]
            offset += FRAME_BYTES

    def _capture_loop(self) -> None:
        capture = _Input(self.input_device)
        try:
            capture.open()
            while not self._stop.is_set():
                near = capture.read(FRAME_BYTES)
                if not near:
                    break
                far = self._take_far(len(near))
                clean = self.canceller.process(near, far)
                if self.uplink_write is not None:
                    try:
                        self.uplink_write(clean)
                    except OSError as exc:
                        LOGGER.warning("Uplink write failed: %s", exc)
                if self.on_clean_frame is not None:
                    self.on_clean_frame(clean, near, far)
        finally:
            capture.close()

    def _take_far(self, nbytes: int) -> bytes:
        with self._far_lock:
            buf = bytes(self._far)
        delay = self._delay_bytes
        if len(buf) <= delay:
            return b"\x00" * nbytes
        end = len(buf) - delay
        start = max(0, end - nbytes)
        chunk = buf[start:end]
        if len(chunk) < nbytes:
            chunk = b"\x00" * (nbytes - len(chunk)) + chunk
        return chunk


def _read_wav_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        raw = wav.readframes(wav.getnframes())
    if width != 2:
        raise ValueError(f"unsupported wav width {width} in {path}")
    if channels == 2:
        import numpy as np

        stereo = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).astype(np.float32)
        raw = stereo.mean(axis=1).clip(-32768, 32767).astype(np.int16).tobytes()
    return raw, rate


class _Output:
    def __init__(self, device: str) -> None:
        self._device = device
        self._sd = None
        self._stream = None
        self._proc: subprocess.Popen[bytes] | None = None

    def open(self) -> None:
        try:
            import sounddevice as sd

            self._sd = sd
            self._stream = sd.RawOutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=_portaudio_device(self._device, kind="output"),
                blocksize=FRAME_SAMPLES,
            )
            self._stream.start()
            return
        except Exception as exc:
            LOGGER.warning("sounddevice output unavailable (%s); using aplay", exc)
        self._proc = subprocess.Popen(
            ["aplay", "-q", "-D", self._device, "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw"],
            stdin=subprocess.PIPE,
        )

    def write(self, frame: bytes) -> None:
        if self._stream is not None:
            self._stream.write(frame)
            return
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(frame)
            self._proc.stdin.flush()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        if self._proc:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.terminate()


class _Input:
    def __init__(self, device: str) -> None:
        self._device = device
        self._stream = None
        self._proc: subprocess.Popen[bytes] | None = None

    def open(self) -> None:
        try:
            import sounddevice as sd

            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=_portaudio_device(self._device, kind="input"),
                blocksize=FRAME_SAMPLES,
            )
            self._stream.start()
            return
        except Exception as exc:
            LOGGER.warning("sounddevice input unavailable (%s); using arecord", exc)
        self._proc = subprocess.Popen(
            [
                "arecord",
                "-D",
                self._device,
                "-f",
                "S16_LE",
                "-r",
                str(SAMPLE_RATE),
                "-c",
                "1",
                "-t",
                "raw",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def read(self, nbytes: int) -> bytes:
        if self._stream is not None:
            data, _overflow = self._stream.read(FRAME_SAMPLES)
            return bytes(data)
        if not self._proc or not self._proc.stdout:
            return b""
        return self._proc.stdout.read(nbytes)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        if self._proc:
            self._proc.terminate()


def _portaudio_device(name: str, *, kind: str):
    if name.isdigit():
        return int(name)
    env_key = "AUDIO_OUTPUT_DEVICE" if kind == "output" else "AUDIO_INPUT_DEVICE"
    override = __import__("os").getenv(env_key, "").strip()
    if override.isdigit():
        return int(override)
    return None
