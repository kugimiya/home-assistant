"""MemoryManager facade: sessions, storage, search, context injection."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from jarvis_pi.memory import fts
from jarvis_pi.memory.config import MemoryConfig, load_memory_config
from jarvis_pi.memory.db import open_database
from jarvis_pi.memory.fusion import rrf_fuse
from jarvis_pi.memory.models import SearchHit, SessionSummaryResult
from jarvis_pi.memory.summarizer import summarize_session
from jarvis_pi.memory.temporal import TemporalLayer
from jarvis_pi.memory.truth_log import append_record

LOGGER = logging.getLogger("jarvis_pi.memory")

ClearTurnsCallback = Callable[[], None]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_fact(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _tags_json(tags: list[str] | None) -> str | None:
    if not tags:
        return None
    cleaned = [t.strip().lower() for t in tags if t.strip()]
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


class MemoryManager:
    def __init__(self, config: MemoryConfig | None = None) -> None:
        self._config = config or load_memory_config()
        self._lock = threading.RLock()
        self._conn, self._fts_enabled = open_database(
            self._config.db_path, self._config.truth_log_path
        )
        self._session_id: str | None = None
        self._session_messages: list[tuple[str, str]] = []
        self._last_interaction: float | None = None
        self._clear_turns: ClearTurnsCallback | None = None

    @property
    def fts_enabled(self) -> bool:
        return self._fts_enabled

    def set_clear_turns_callback(self, callback: ClearTurnsCallback | None) -> None:
        self._clear_turns = callback

    def ensure_session(self) -> str:
        with self._lock:
            now = time.monotonic()
            if self._session_id and self._last_interaction is not None:
                if now - self._last_interaction > self._config.session_timeout_sec:
                    self._end_session_sync(summarize=True)
            if not self._session_id:
                self._start_session()
            return self._session_id or ""

    def touch_interaction(self) -> None:
        with self._lock:
            self._last_interaction = time.monotonic()

    def record_exchange(self, user_text: str, assistant_text: str) -> None:
        with self._lock:
            self.ensure_session()
            self._session_messages.append(("user", user_text))
            if assistant_text.strip():
                self._session_messages.append(("assistant", assistant_text))
            self._last_interaction = time.monotonic()

    def record_user_only(self, user_text: str) -> None:
        with self._lock:
            self.ensure_session()
            self._session_messages.append(("user", user_text))
            self._last_interaction = time.monotonic()

    def end_session(self, *, summarize: bool = True, background: bool = True) -> None:
        with self._lock:
            self._end_session_sync(summarize=summarize, background=background)

    def shutdown(self) -> None:
        with self._lock:
            self._end_session_sync(summarize=True, background=False)
            self._conn.close()

    def _start_session(self) -> None:
        session_id = str(uuid.uuid4())
        started = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                "INSERT INTO sessions (id, started_at, status) VALUES (?, ?, 'active')",
                (session_id, started),
            )
        append_record(
            self._config.truth_log_path,
            {"kind": "session", "id": session_id, "started_at": started, "status": "active"},
        )
        self._session_id = session_id
        self._session_messages = []
        LOGGER.info("Memory session started id=%s", session_id[:8])

    def _end_session_sync(self, *, summarize: bool, background: bool = True) -> None:
        session_id = self._session_id
        messages = list(self._session_messages)
        self._session_id = None
        self._session_messages = []
        if self._clear_turns:
            self._clear_turns()

        if not session_id:
            return

        ended = _utc_now_iso()
        started_row = self._conn.execute(
            "SELECT started_at FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        started_at = started_row["started_at"] if started_row else ended
        with self._conn:
            self._conn.execute(
                """
                UPDATE sessions SET ended_at = ?, status = ?
                WHERE id = ?
                """,
                (ended, "pending_summary" if summarize and messages else "ended", session_id),
            )
        append_record(
            self._config.truth_log_path,
            {
                "kind": "session",
                "id": session_id,
                "started_at": started_at,
                "ended_at": ended,
                "status": "pending_summary" if summarize and messages else "ended",
            },
        )
        LOGGER.info(
            "Memory session ended id=%s messages=%d summarize=%s",
            session_id[:8],
            len(messages),
            summarize,
        )

        if summarize and messages:
            if background:
                thread = threading.Thread(
                    target=self._summarize_background,
                    args=(session_id, messages),
                    daemon=True,
                    name="memory-summarize",
                )
                thread.start()
            else:
                self._summarize_background(session_id, messages)

    def _summarize_background(self, session_id: str, messages: list[tuple[str, str]]) -> None:
        result = summarize_session(messages)
        if result is None:
            with self._lock:
                with self._conn:
                    self._conn.execute(
                        "UPDATE sessions SET status = ? WHERE id = ?",
                        ("summary_failed", session_id),
                    )
            return
        try:
            self._persist_summary(session_id, result)
        except Exception:
            LOGGER.exception("Failed to persist session summary")
            with self._lock:
                with self._conn:
                    self._conn.execute(
                        "UPDATE sessions SET status = ? WHERE id = ?",
                        ("summary_failed", session_id),
                    )

    def _persist_summary(self, session_id: str, result: SessionSummaryResult) -> None:
        tags_json = _tags_json(result.tags)
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO episodes (session_id, summary, tags, importance)
                    VALUES (?, ?, ?, ?)
                    """,
                    (session_id, result.summary, tags_json, result.importance),
                )
                episode_id = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                self._conn.execute(
                    "UPDATE sessions SET summary = ?, status = ? WHERE id = ?",
                    (result.summary, "ended", session_id),
                )

                for fact in result.extracted_facts:
                    self._insert_fact_row(
                        fact.fact,
                        source="model_inferred",
                        confidence=fact.confidence,
                        tags=result.tags,
                        conn=self._conn,
                        write_log=False,
                    )

                for trait in result.traits:
                    self._upsert_trait_row(
                        trait.trait,
                        trait.value,
                        trait.confidence,
                        conn=self._conn,
                        write_log=False,
                    )

            append_record(
                self._config.truth_log_path,
                {
                    "kind": "episode",
                    "id": episode_id,
                    "session_id": session_id,
                    "summary": result.summary,
                    "tags": tags_json,
                    "importance": result.importance,
                    "created_at": _utc_now_iso(),
                },
            )
            for fact in result.extracted_facts:
                append_record(
                    self._config.truth_log_path,
                    {
                        "kind": "fact",
                        "fact_text": fact.fact,
                        "fact_norm": _normalize_fact(fact.fact),
                        "source": "model_inferred",
                        "confidence": fact.confidence,
                        "tags": tags_json,
                        "created_at": _utc_now_iso(),
                    },
                )
            for trait in result.traits:
                append_record(
                    self._config.truth_log_path,
                    {
                        "kind": "trait",
                        "trait": trait.trait,
                        "value": trait.value,
                        "confidence": trait.confidence,
                        "last_updated": _utc_now_iso(),
                    },
                )

        LOGGER.info(
            "Session summary stored session=%s episode=%s facts=%d traits=%d",
            session_id[:8],
            episode_id,
            len(result.extracted_facts),
            len(result.traits),
        )

    def _insert_fact_row(
        self,
        fact_text: str,
        *,
        source: str,
        confidence: str,
        tags: list[str] | None,
        conn,
        write_log: bool = True,
    ) -> int:
        norm = _normalize_fact(fact_text)
        tags_json = _tags_json(tags)
        existing = conn.execute(
            "SELECT id FROM facts WHERE fact_norm = ?", (norm,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE facts SET fact_text = ?, source = ?, confidence = ?, tags = ?
                WHERE id = ?
                """,
                (fact_text.strip(), source, confidence, tags_json, existing["id"]),
            )
            fact_id = int(existing["id"])
        else:
            conn.execute(
                """
                INSERT INTO facts (fact_text, fact_norm, source, confidence, tags)
                VALUES (?, ?, ?, ?, ?)
                """,
                (fact_text.strip(), norm, source, confidence, tags_json),
            )
            fact_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        if write_log:
            append_record(
                self._config.truth_log_path,
                {
                    "kind": "fact",
                    "id": fact_id,
                    "fact_text": fact_text.strip(),
                    "fact_norm": norm,
                    "source": source,
                    "confidence": confidence,
                    "tags": tags_json,
                    "created_at": _utc_now_iso(),
                },
            )
        return fact_id

    def _upsert_trait_row(
        self,
        trait: str,
        value: str,
        confidence: float,
        *,
        conn,
        write_log: bool = True,
    ) -> None:
        conn.execute(
            """
            INSERT INTO user_traits (trait, value, confidence, last_updated)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(trait) DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                last_updated = datetime('now')
            """,
            (trait.strip(), value.strip(), confidence),
        )
        if write_log:
            append_record(
                self._config.truth_log_path,
                {
                    "kind": "trait",
                    "trait": trait.strip(),
                    "value": value.strip(),
                    "confidence": confidence,
                    "last_updated": _utc_now_iso(),
                },
            )

    def add_fact(
        self,
        fact: str,
        source: str = "user_explicit",
        confidence: str = "INFERRED",
        tags: list[str] | None = None,
    ) -> int:
        with self._lock:
            with self._conn:
                return self._insert_fact_row(
                    fact,
                    source=source,
                    confidence=confidence,
                    tags=tags,
                    conn=self._conn,
                    write_log=True,
                )

    def search(
        self,
        query: str,
        *,
        layer: TemporalLayer = "all",
        limit: int = 5,
    ) -> list[SearchHit]:
        per_channel = max(limit, 5)
        with self._lock:
            facts = fts.search_facts(
                self._conn,
                query,
                config=self._config,
                layer=layer,
                limit=per_channel,
                fts_enabled=self._fts_enabled,
            )
            episodes = fts.search_episodes(
                self._conn,
                query,
                config=self._config,
                layer=layer,
                limit=per_channel,
                fts_enabled=self._fts_enabled,
            )
            traits = fts.search_traits(
                self._conn,
                query,
                config=self._config,
                layer=layer,
                limit=per_channel,
                fts_enabled=self._fts_enabled,
            )

        fused = rrf_fuse(
            [facts, episodes, traits],
            k=self._config.rrf_k,
        )
        return fused[:limit]

    def get_profile(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT trait, value, confidence, last_updated FROM user_traits ORDER BY trait"
            ).fetchall()
        return [
            {
                "trait": row["trait"],
                "value": row["value"],
                "confidence": row["confidence"],
                "last_updated": row["last_updated"],
            }
            for row in rows
        ]

    def get_recent_episodes(self, limit: int = 3) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, summary, tags, importance, created_at
                FROM episodes
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "summary": row["summary"],
                "tags": row["tags"],
                "importance": row["importance"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_context_for_prompt(self, last_user_text: str) -> str:
        profile = self.get_profile()
        hits = self.search(last_user_text, limit=5) if last_user_text.strip() else []

        parts: list[str] = []
        if profile:
            lines = [f"- {p['trait']}: {p['value']}" for p in profile]
            parts.append("Профиль пользователя:\n" + "\n".join(lines))

        if hits:
            mem_lines = [f"- [{h.channel}] {h.text}" for h in hits]
            parts.append("Релевантная память:\n" + "\n".join(mem_lines))

        if not parts:
            return ""

        block = "\n\n".join(parts)
        max_len = self._config.context_max_chars
        if len(block) > max_len:
            block = block[: max_len - 3] + "..."
        return block


_manager: MemoryManager | None = None
_manager_lock = threading.Lock()


def get_memory_manager() -> MemoryManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = MemoryManager()
        return _manager
