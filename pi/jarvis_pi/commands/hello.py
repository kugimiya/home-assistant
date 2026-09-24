"""Hello command."""

from __future__ import annotations

from .types import CommandExecutionResult, StreamCallback

TRIGGERS = ("привет",)


def get_resolve_phrase() -> str:
    return "Поняла команду привет."


def handle(payload: str, stream_callback: StreamCallback | None = None) -> CommandExecutionResult:
    del payload, stream_callback
    return CommandExecutionResult(reply="Привет. Я на связи.")
