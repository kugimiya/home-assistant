"""Memory subsystem configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@dataclass(frozen=True)
class MemoryConfig:
    db_path: Path
    truth_log_path: Path
    session_timeout_sec: float
    hot_hours: float
    warm_days: float
    bm25_fact_text_weight: float
    bm25_tags_weight: float
    context_max_chars: int
    rrf_k: int


def load_memory_config() -> MemoryConfig:
    db_raw = os.getenv("MEMORY_DB_PATH", "").strip()
    if db_raw:
        db_path = Path(db_raw)
    else:
        db_path = _DEFAULT_DATA_DIR / "memory.db"

    log_raw = os.getenv("MEMORY_TRUTH_LOG_PATH", "").strip()
    if log_raw:
        truth_log_path = Path(log_raw)
    else:
        truth_log_path = db_path.parent / "memory_truth.jsonl"

    return MemoryConfig(
        db_path=db_path,
        truth_log_path=truth_log_path,
        session_timeout_sec=float(os.getenv("MEMORY_SESSION_TIMEOUT_SEC", "1800")),
        hot_hours=float(os.getenv("MEMORY_HOT_HOURS", "3")),
        warm_days=float(os.getenv("MEMORY_WARM_DAYS", "7")),
        bm25_fact_text_weight=float(os.getenv("MEMORY_BM25_FACT_WEIGHT", "3.0")),
        bm25_tags_weight=float(os.getenv("MEMORY_BM25_TAGS_WEIGHT", "1.0")),
        context_max_chars=int(os.getenv("MEMORY_CONTEXT_MAX_CHARS", "2000")),
        rrf_k=int(os.getenv("MEMORY_RRF_K", "60")),
    )
