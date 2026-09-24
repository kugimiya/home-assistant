"""Piper synthesis helper."""

from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path


def synthesize_pcm(
    text: str,
    piper_bin: Path,
    model_path: Path,
    config_path: Path | None,
) -> tuple[bytes, int]:
    text = text.strip()
    if not text:
        return b"", 22050

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        wav_path = Path(tmp_wav.name)

    command = [str(piper_bin), "--model", str(model_path), "--output_file", str(wav_path)]
    if config_path and config_path.exists():
        command.extend(["--config", str(config_path)])

    try:
        subprocess.run(
            command,
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        with wave.open(str(wav_path), "rb") as wav_file:
            if wav_file.getsampwidth() != 2:
                raise ValueError("Piper output must be 16-bit PCM")
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            frames = wav_file.readframes(wav_file.getnframes())
        if channels == 2:
            import array

            samples = array.array("h")
            samples.frombytes(frames)
            mono = array.array("h", (samples[i] for i in range(0, len(samples), 2)))
            frames = mono.tobytes()
        return frames, sample_rate
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except OSError:
            pass
