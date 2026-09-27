"""Shared pytest fixtures for memory tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis_pi.memory.config import MemoryConfig
from jarvis_pi.memory.manager import MemoryManager


@pytest.fixture
def memory_paths(tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / "memory.db"
    log = tmp_path / "memory_truth.jsonl"
    return db, log


@pytest.fixture
def memory_config(memory_paths: tuple[Path, Path]) -> MemoryConfig:
    db, log = memory_paths
    return MemoryConfig(
        db_path=db,
        truth_log_path=log,
        session_timeout_sec=1800.0,
        hot_hours=3.0,
        warm_days=7.0,
        bm25_fact_text_weight=3.0,
        bm25_tags_weight=1.0,
        context_max_chars=2000,
        rrf_k=60,
    )


@pytest.fixture
def manager(memory_config: MemoryConfig) -> MemoryManager:
    mgr = MemoryManager(memory_config)
    yield mgr
    mgr.shutdown()
