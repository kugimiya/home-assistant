"""Background job models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass
class Job:
    id: str
    title: str
    prompt: str
    brief: str
    status: JobStatus
    parent_id: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    progress_note: str | None
    result_text: str | None
    spoken_summary: str | None
    error_text: str | None
    model: str | None
    tool_rounds: int
    api_calls: int
    introspection_count: int
    budget_extensions: int
    current_api_budget: int


@dataclass
class JobStep:
    id: int
    job_id: str
    step_index: int
    kind: str
    tool_name: str | None
    detail: str
    created_at: str
