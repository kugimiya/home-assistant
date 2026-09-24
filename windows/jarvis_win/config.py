"""Runtime configuration for the Windows audio service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class WindowsConfig:
    pcm_listen_host: str
    pcm_listen_port: int
    control_listen_host: str
    control_listen_port: int
    vosk_model_path: Path
    piper_bin: Path
    piper_model: Path
    piper_config: Path
    sample_rate: int


def load_config() -> WindowsConfig:
    vosk_path = Path(os.getenv("VOSK_MODEL_PATH", "models/vosk-model-ru-0.42"))
    piper_bin = Path(os.getenv("PIPER_BIN", "third_party/piper/piper.exe"))
    piper_model = Path(os.getenv("PIPER_MODEL", "models/ru_RU-irina-medium.onnx"))
    piper_config = Path(os.getenv("PIPER_CONFIG", "models/ru_RU-irina-medium.onnx.json"))

    if not vosk_path.exists():
        raise ValueError(f"Vosk model not found: {vosk_path}")
    if not piper_bin.exists():
        raise ValueError(f"Piper binary not found: {piper_bin}")
    if not piper_model.exists():
        raise ValueError(f"Piper model not found: {piper_model}")

    return WindowsConfig(
        pcm_listen_host=os.getenv("PCM_LISTEN_HOST", "0.0.0.0"),
        pcm_listen_port=int(os.getenv("PCM_LISTEN_PORT", "9700")),
        control_listen_host=os.getenv("CONTROL_LISTEN_HOST", "0.0.0.0"),
        control_listen_port=int(os.getenv("CONTROL_LISTEN_PORT", "9701")),
        vosk_model_path=vosk_path,
        piper_bin=piper_bin,
        piper_model=piper_model,
        piper_config=piper_config if piper_config.exists() else piper_model.with_suffix(".onnx.json"),
        sample_rate=int(os.getenv("SAMPLE_RATE", "16000")),
    )
