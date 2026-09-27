from pathlib import Path

from jarvis_pi.memory.config import MemoryConfig
from jarvis_pi.memory.db import open_database, rebuild_from_truth_log
from jarvis_pi.memory.manager import MemoryManager
from jarvis_pi.memory.truth_log import append_record


def test_rebuild_from_truth_log_after_corruption(memory_paths: tuple[Path, Path]) -> None:
    db_path, log_path = memory_paths
    config = MemoryConfig(
        db_path=db_path,
        truth_log_path=log_path,
        session_timeout_sec=1800,
        hot_hours=3,
        warm_days=7,
        bm25_fact_text_weight=3.0,
        bm25_tags_weight=1.0,
        context_max_chars=2000,
        rrf_k=60,
    )
    mgr = MemoryManager(config)
    mgr.add_fact("тестовый факт для recovery", confidence="EXTRACTED")
    mgr.shutdown()

    db_path.write_bytes(b"not a sqlite file")
    conn, _ = open_database(db_path, log_path)
    row = conn.execute("SELECT fact_text FROM facts").fetchone()
    conn.close()
    assert row is not None
    assert "recovery" in row[0]


def test_rebuild_from_jsonl_directly(memory_paths: tuple[Path, Path]) -> None:
    db_path, log_path = memory_paths
    append_record(
        log_path,
        {
            "kind": "fact",
            "fact_text": "из лога",
            "fact_norm": "из лога",
            "source": "user_explicit",
            "confidence": "EXTRACTED",
        },
    )
    conn, _ = open_database(db_path, log_path)
    if not conn.execute("SELECT 1 FROM facts LIMIT 1").fetchone():
        rebuild_from_truth_log(conn, log_path)
    row = conn.execute("SELECT fact_text FROM facts").fetchone()
    conn.close()
    assert row is not None
