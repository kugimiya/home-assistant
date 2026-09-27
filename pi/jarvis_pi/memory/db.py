"""SQLite schema, FTS5, migrations, and recovery."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from jarvis_pi.memory.truth_log import iter_records

LOGGER = logging.getLogger("jarvis_pi.memory.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    summary TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    summary TEXT NOT NULL,
    tags TEXT,
    importance INTEGER DEFAULT 50,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_text TEXT NOT NULL,
    fact_norm TEXT NOT NULL,
    source TEXT,
    confidence TEXT DEFAULT 'INFERRED',
    tags TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_norm ON facts(fact_norm);

CREATE TABLE IF NOT EXISTS user_traits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trait TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.9,
    last_updated TEXT DEFAULT (datetime('now')),
    UNIQUE(trait)
);
"""

_FTS5_AVAILABLE: bool | None = None


def fts5_available(conn: sqlite3.Connection) -> bool:
    global _FTS5_AVAILABLE
    if _FTS5_AVAILABLE is not None:
        return _FTS5_AVAILABLE
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(content)")
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
        _FTS5_AVAILABLE = True
    except sqlite3.OperationalError:
        _FTS5_AVAILABLE = False
    return _FTS5_AVAILABLE


def _fts_schema() -> str:
    return """
CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    summary, tags,
    content='episodes',
    content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    fact_text, tags,
    content='facts',
    content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS user_traits_fts USING fts5(
    trait, value,
    content='user_traits',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, summary, tags) VALUES (new.id, new.summary, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary, tags)
    VALUES('delete', old.id, old.summary, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary, tags)
    VALUES('delete', old.id, old.summary, old.tags);
    INSERT INTO episodes_fts(rowid, summary, tags) VALUES (new.id, new.summary, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, fact_text, tags) VALUES (new.id, new.fact_text, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, fact_text, tags)
    VALUES('delete', old.id, old.fact_text, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, fact_text, tags)
    VALUES('delete', old.id, old.fact_text, old.tags);
    INSERT INTO facts_fts(rowid, fact_text, tags) VALUES (new.id, new.fact_text, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS user_traits_ai AFTER INSERT ON user_traits BEGIN
    INSERT INTO user_traits_fts(rowid, trait, value) VALUES (new.id, new.trait, new.value);
END;
CREATE TRIGGER IF NOT EXISTS user_traits_ad AFTER DELETE ON user_traits BEGIN
    INSERT INTO user_traits_fts(user_traits_fts, rowid, trait, value)
    VALUES('delete', old.id, old.trait, old.value);
END;
CREATE TRIGGER IF NOT EXISTS user_traits_au AFTER UPDATE ON user_traits BEGIN
    INSERT INTO user_traits_fts(user_traits_fts, rowid, trait, value)
    VALUES('delete', old.id, old.trait, old.value);
    INSERT INTO user_traits_fts(rowid, trait, value) VALUES (new.id, new.trait, new.value);
END;
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def integrity_ok(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return row is not None and str(row[0]).lower() == "ok"
    except sqlite3.DatabaseError:
        return False


def init_schema(conn: sqlite3.Connection, *, use_fts: bool) -> None:
    conn.executescript(_SCHEMA_SQL)
    if use_fts:
        conn.executescript(_fts_schema())
        conn.execute("INSERT INTO episodes_fts(episodes_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO facts_fts(facts_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO user_traits_fts(user_traits_fts) VALUES('rebuild')")
    conn.commit()


def rebuild_fts(conn: sqlite3.Connection) -> None:
    if not fts5_available(conn):
        return
    for table in ("episodes_fts", "facts_fts", "user_traits_fts"):
        try:
            conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')")
        except sqlite3.OperationalError:
            pass
    conn.commit()


def rebuild_from_truth_log(conn: sqlite3.Connection, truth_log_path: Path) -> None:
    use_fts = fts5_available(conn)
    conn.executescript(
        """
        DROP TABLE IF EXISTS episodes_fts;
        DROP TABLE IF EXISTS facts_fts;
        DROP TABLE IF EXISTS user_traits_fts;
        DROP TABLE IF EXISTS episodes;
        DROP TABLE IF EXISTS facts;
        DROP TABLE IF EXISTS user_traits;
        DROP TABLE IF EXISTS sessions;
        """
    )
    init_schema(conn, use_fts=use_fts)

    sessions_merged: dict[str, dict] = {}
    for rec in iter_records(truth_log_path):
        if rec.get("kind") == "session" and rec.get("id"):
            sid = str(rec["id"])
            merged = sessions_merged.get(sid, {})
            merged.update({k: v for k, v in rec.items() if k != "kind"})
            sessions_merged[sid] = merged
    for sid, rec in sessions_merged.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions (id, started_at, ended_at, summary, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                sid,
                rec.get("started_at") or _utc_now_placeholder(),
                rec.get("ended_at"),
                rec.get("summary"),
                rec.get("status", "ended"),
            ),
        )

    for rec in iter_records(truth_log_path):
        kind = rec.get("kind")
        if kind == "session":
            continue
        elif kind == "episode":
            conn.execute(
                """
                INSERT INTO episodes (id, session_id, summary, tags, importance, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.get("id"),
                    rec.get("session_id"),
                    rec["summary"],
                    rec.get("tags"),
                    rec.get("importance", 50),
                    rec.get("created_at"),
                ),
            )
        elif kind == "fact":
            conn.execute(
                """
                INSERT INTO facts (id, fact_text, fact_norm, source, confidence, tags, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.get("id"),
                    rec["fact_text"],
                    rec.get("fact_norm") or _normalize_fact(rec["fact_text"]),
                    rec.get("source"),
                    rec.get("confidence", "INFERRED"),
                    rec.get("tags"),
                    rec.get("created_at"),
                ),
            )
        elif kind == "trait":
            conn.execute(
                """
                INSERT INTO user_traits (id, trait, value, confidence, last_updated)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    rec.get("id"),
                    rec["trait"],
                    rec["value"],
                    rec.get("confidence", 0.9),
                    rec.get("last_updated"),
                ),
            )
    conn.commit()
    if use_fts:
        rebuild_fts(conn)


def _normalize_fact(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _utc_now_placeholder() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _recover_database(db_path: Path, truth_log_path: Path) -> tuple[sqlite3.Connection, bool]:
    if db_path.is_file():
        db_path.unlink()
    conn = connect(db_path)
    use_fts = fts5_available(conn)
    if truth_log_path.is_file():
        rebuild_from_truth_log(conn, truth_log_path)
    else:
        init_schema(conn, use_fts=use_fts)
    return conn, use_fts


def open_database(db_path: Path, truth_log_path: Path) -> tuple[sqlite3.Connection, bool]:
    """
    Open DB, recover if needed. Returns (connection, fts_enabled).
    """
    try:
        conn = connect(db_path)
    except sqlite3.DatabaseError:
        LOGGER.warning("SQLite file unreadable; rebuilding from truth log")
        return _recover_database(db_path, truth_log_path)

    use_fts = fts5_available(conn)

    if not integrity_ok(conn):
        LOGGER.warning("SQLite integrity check failed; rebuilding from truth log")
        conn.close()
        return _recover_database(db_path, truth_log_path)

    try:
        conn.execute("SELECT 1 FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        init_schema(conn, use_fts=use_fts)
        if truth_log_path.is_file():
            rebuild_from_truth_log(conn, truth_log_path)
        return conn, use_fts

    if use_fts:
        try:
            conn.execute("SELECT 1 FROM facts_fts LIMIT 1")
        except sqlite3.OperationalError:
            conn.executescript(_fts_schema())
            rebuild_fts(conn)

    return conn, use_fts
