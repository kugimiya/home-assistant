"""JSON line protocol shared with the Windows audio service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def encode_message(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def decode_message(line: bytes) -> dict[str, Any]:
    return json.loads(line.decode("utf-8"))


@dataclass(frozen=True)
class AudioHeader:
    request_id: str
    sample_rate: int
    nbytes: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AudioHeader:
        return cls(
            request_id=str(payload.get("id", "")),
            sample_rate=int(payload.get("sample_rate", 22050)),
            nbytes=int(payload.get("nbytes", 0)),
        )
