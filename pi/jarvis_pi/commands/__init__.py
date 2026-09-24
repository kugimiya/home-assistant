"""Command registry and dispatch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from jarvis_pi.wake import normalize_text

from . import hello, think, weather
from .types import CommandExecutionResult, StreamCallback

CommandHandler = Callable[[str, StreamCallback | None], CommandExecutionResult]
ResolvePhraseGetter = Callable[[], str]


@dataclass(frozen=True)
class DispatchResult:
    handler: CommandHandler
    resolve_phrase: str
    payload: str

_REGISTRY: list[tuple[tuple[str, ...], CommandHandler, ResolvePhraseGetter]] = [
    (hello.TRIGGERS, hello.handle, hello.get_resolve_phrase),
    (think.TRIGGERS, think.handle, think.get_resolve_phrase),
    (weather.TRIGGERS, weather.handle, weather.get_resolve_phrase),
]


def dispatch_command(text: str) -> DispatchResult | None:
    normalized = normalize_text(text)
    for triggers, handler, resolve_phrase_getter in _REGISTRY:
        matched_triggers = [trigger for trigger in triggers if trigger in normalized]
        if not matched_triggers:
            continue
        matched_trigger = max(matched_triggers, key=len)
        start_idx = normalized.find(matched_trigger)
        payload = normalized[start_idx + len(matched_trigger) :].strip()
        return DispatchResult(
            handler=handler,
            resolve_phrase=resolve_phrase_getter(),
            payload=payload,
        )
    return None


def list_supported_triggers() -> list[str]:
    return [trigger for triggers, _, _ in _REGISTRY for trigger in triggers]
