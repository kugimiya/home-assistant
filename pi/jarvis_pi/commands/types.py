"""Shared types for command handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

StreamCallback = Callable[[str], None]


@dataclass(frozen=True)
class CommandExecutionResult:
    reply: str
    spoken_during_handle: bool = False
    end_session: bool = False
