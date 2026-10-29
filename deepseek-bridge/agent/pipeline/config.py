"""Pipeline configuration from environment."""

from __future__ import annotations

import os
from pathlib import Path

from agent.config import env_flag
from agent.memory.config import load_memory_config

_DEFAULT_MAX_CONCURRENT = 1
_DEFAULT_JOB_MAX_TOOL_ROUNDS = 24
_DEFAULT_JOB_STEP_TIMEOUT = 120
_DEFAULT_JOB_MAX_API_CALLS = 16
_DEFAULT_JOB_MAX_API_CALLS_TOTAL = 48
_DEFAULT_JOB_MAX_INTROSPECTIONS = 3
_DEFAULT_JOB_MAX_DEPTH = 2
_DEFAULT_RETENTION_DAYS = 30


def pipeline_enabled() -> bool:
    return env_flag("BRIDGE_PIPELINE", False)


def jobs_db_path() -> Path:
    raw = os.getenv("JOBS_DB_PATH", "").strip()
    if raw:
        return Path(raw)
    memory = load_memory_config()
    return memory.db_path.parent / "jobs.db"


def max_concurrent_jobs() -> int:
    raw = os.getenv("BRIDGE_MAX_CONCURRENT_JOBS", "").strip()
    if not raw:
        return _DEFAULT_MAX_CONCURRENT
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_CONCURRENT


def job_max_tool_rounds() -> int:
    raw = os.getenv("BRIDGE_JOB_MAX_TOOL_ROUNDS", "").strip()
    if not raw:
        return _DEFAULT_JOB_MAX_TOOL_ROUNDS
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_JOB_MAX_TOOL_ROUNDS


def job_step_timeout_sec() -> float:
    raw = os.getenv("BRIDGE_JOB_STEP_TIMEOUT_SEC", "").strip()
    if not raw:
        return float(_DEFAULT_JOB_STEP_TIMEOUT)
    try:
        return max(10.0, float(raw))
    except ValueError:
        return float(_DEFAULT_JOB_STEP_TIMEOUT)


def job_max_api_calls() -> int:
    raw = os.getenv("BRIDGE_JOB_MAX_API_CALLS", "").strip()
    if not raw:
        return _DEFAULT_JOB_MAX_API_CALLS
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_JOB_MAX_API_CALLS


def job_max_api_calls_total() -> int:
    raw = os.getenv("BRIDGE_JOB_MAX_API_CALLS_TOTAL", "").strip()
    if not raw:
        return _DEFAULT_JOB_MAX_API_CALLS_TOTAL
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_JOB_MAX_API_CALLS_TOTAL


def job_api_calls_extension() -> int:
    raw = os.getenv("BRIDGE_JOB_API_CALLS_EXTENSION", "").strip()
    if not raw:
        return job_max_api_calls()
    try:
        return max(1, int(raw))
    except ValueError:
        return job_max_api_calls()


def job_max_introspections() -> int:
    raw = os.getenv("BRIDGE_JOB_MAX_INTROSPECTIONS", "").strip()
    if not raw:
        return _DEFAULT_JOB_MAX_INTROSPECTIONS
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_JOB_MAX_INTROSPECTIONS


def job_max_depth() -> int:
    raw = os.getenv("BRIDGE_JOB_MAX_DEPTH", "").strip()
    if not raw:
        return _DEFAULT_JOB_MAX_DEPTH
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_JOB_MAX_DEPTH


def jobs_retention_days() -> int:
    raw = os.getenv("JOBS_RETENTION_DAYS", "").strip()
    if not raw:
        return _DEFAULT_RETENTION_DAYS
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_RETENTION_DAYS


def job_python_timeout_sec() -> int:
    raw = os.getenv("BRIDGE_JOB_PYTHON_TIMEOUT_SEC", "").strip()
    if not raw:
        return 60
    try:
        return max(1, int(raw))
    except ValueError:
        return 60


def job_tool_disabled(name: str) -> bool:
    key = f"BRIDGE_JOB_TOOL_{name.upper()}"
    raw = os.getenv(key, "").strip()
    if not raw:
        defaults_off = {"rewrite_self", "reset_self", "control_home"}
        return name in defaults_off
    return raw.lower() in ("0", "false", "no", "off")


def use_stub_worker() -> bool:
    return env_flag("BRIDGE_PIPELINE_STUB_WORKER", False)
