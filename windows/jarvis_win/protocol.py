"""JSON line protocol shared with the Pi edge service.

Control: hello, speak, stt_reset, health, reload_modules; responses ready, audio,
health, reload_result, error; STT events partial/final.
"""

from __future__ import annotations

import json
from typing import Any


def encode_message(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def decode_message(line: bytes) -> dict[str, Any]:
    return json.loads(line.decode("utf-8"))
