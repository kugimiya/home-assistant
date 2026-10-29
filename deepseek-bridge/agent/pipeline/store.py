"""SQLite persistence for background jobs."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.pipeline.config import job_max_api_calls, jobs_db_path
from agent.pipeline.models import Job, JobStatus, JobStep

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    brief TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    parent_id TEXT REFERENCES jobs(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    progress_note TEXT,
    result_text TEXT,
    spoken_summary TEXT,
    error_text TEXT,
    model TEXT,
    tool_rounds INTEGER NOT NULL DEFAULT 0,
    api_calls INTEGER NOT NULL DEFAULT 0,
    introspection_count INTEGER NOT NULL DEFAULT 0,
    budget_extensions INTEGER NOT NULL DEFAULT 0,
    current_api_budget INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_id);

CREATE TABLE IF NOT EXISTS job_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    step_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    tool_name TEXT,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_steps_job ON job_steps(job_id, step_index);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize_detail(text: str, limit: int = 500) -> str:
    cleaned = " ".join(text.split())
    upper = cleaned.upper()
    for token in ("TOKEN", "SECRET", "PASSWORD", "API_KEY"):
        if token in upper:
            cleaned = "[redacted detail]"
            break
    if len(cleaned) > limit:
        return cleaned[: limit - 1] + "…"
    return cleaned


class JobStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or jobs_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            id=str(row["id"]),
            title=str(row["title"]),
            prompt=str(row["prompt"]),
            brief=str(row["brief"] or ""),
            status=JobStatus(str(row["status"])),
            parent_id=row["parent_id"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            progress_note=row["progress_note"],
            result_text=row["result_text"],
            spoken_summary=row["spoken_summary"],
            error_text=row["error_text"],
            model=row["model"],
            tool_rounds=int(row["tool_rounds"] or 0),
            api_calls=int(row["api_calls"] or 0),
            introspection_count=int(row["introspection_count"] or 0),
            budget_extensions=int(row["budget_extensions"] or 0),
            current_api_budget=int(row["current_api_budget"] or 0),
        )

    def create_job(
        self,
        *,
        title: str,
        prompt: str,
        brief: str = "",
        parent_id: str | None = None,
    ) -> Job:
        job_id = str(uuid.uuid4())
        now = _now_iso()
        budget = job_max_api_calls()
        self._conn.execute(
            """
            INSERT INTO jobs (
                id, title, prompt, brief, status, parent_id,
                created_at, updated_at, current_api_budget
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                title.strip(),
                prompt.strip(),
                brief.strip(),
                JobStatus.QUEUED.value,
                parent_id,
                now,
                now,
                budget,
            ),
        )
        self._conn.commit()
        job = self.get_job(job_id)
        assert job is not None
        return job

    def get_job(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def update_job(self, job_id: str, **fields: object) -> None:
        if not fields:
            return
        allowed = {
            "title",
            "prompt",
            "brief",
            "status",
            "started_at",
            "finished_at",
            "progress_note",
            "result_text",
            "spoken_summary",
            "error_text",
            "model",
            "tool_rounds",
            "api_calls",
            "introspection_count",
            "budget_extensions",
            "current_api_budget",
        }
        parts: list[str] = []
        values: list[object] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "status" and isinstance(value, JobStatus):
                value = value.value
            parts.append(f"{key} = ?")
            values.append(value)
        parts.append("updated_at = ?")
        values.append(_now_iso())
        values.append(job_id)
        self._conn.execute(
            f"UPDATE jobs SET {', '.join(parts)} WHERE id = ?",
            values,
        )
        self._conn.commit()

    def increment_api_calls(self, job_id: str, delta: int = 1) -> int:
        self._conn.execute(
            "UPDATE jobs SET api_calls = api_calls + ?, updated_at = ? WHERE id = ?",
            (delta, _now_iso(), job_id),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT api_calls FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def append_step(
        self,
        job_id: str,
        *,
        kind: str,
        detail: str,
        tool_name: str | None = None,
    ) -> None:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(step_index), -1) + 1 FROM job_steps WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        step_index = int(row[0]) if row else 0
        self._conn.execute(
            """
            INSERT INTO job_steps (job_id, step_index, kind, tool_name, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                step_index,
                kind,
                tool_name,
                _sanitize_detail(detail),
                _now_iso(),
            ),
        )
        self._conn.commit()

    def list_steps(self, job_id: str) -> list[JobStep]:
        rows = self._conn.execute(
            """
            SELECT id, job_id, step_index, kind, tool_name, detail, created_at
            FROM job_steps WHERE job_id = ? ORDER BY step_index
            """,
            (job_id,),
        ).fetchall()
        return [
            JobStep(
                id=int(r["id"]),
                job_id=str(r["job_id"]),
                step_index=int(r["step_index"]),
                kind=str(r["kind"]),
                tool_name=r["tool_name"],
                detail=str(r["detail"]),
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]

    def list_jobs(
        self,
        *,
        status: JobStatus | None = None,
        limit: int = 10,
        parent_id: str | None = None,
    ) -> list[Job]:
        query = "SELECT * FROM jobs WHERE 1=1"
        params: list[object] = []
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if parent_id is not None:
            query += " AND parent_id = ?"
            params.append(parent_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, limit))
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_job(r) for r in rows]

    def find_by_title(self, query: str, limit: int = 5) -> list[Job]:
        q = query.strip()
        if not q:
            return []
        pattern = f"%{q.replace('%', '').replace('_', '')}%"
        rows = self._conn.execute(
            """
            SELECT * FROM jobs
            WHERE title LIKE ? OR prompt LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (pattern, pattern, max(1, limit)),
        ).fetchall()
        if rows:
            return [self._row_to_job(r) for r in rows]
        return self.search_jobs(q, limit=limit)

    def search_jobs(self, query: str, limit: int = 5) -> list[Job]:
        return self.find_by_title(query, limit=limit)

    def mark_canceled(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if job is None:
            return False
        if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED):
            return False
        self.update_job(
            job_id,
            status=JobStatus.CANCELED,
            finished_at=_now_iso(),
            progress_note="Отменено пользователем.",
        )
        return True

    def is_canceled(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        return job is not None and job.status == JobStatus.CANCELED

    def requeue_running_jobs(self) -> int:
        cur = self._conn.execute(
            """
            UPDATE jobs SET status = ?, updated_at = ?, progress_note = ?
            WHERE status = ?
            """,
            (
                JobStatus.QUEUED.value,
                _now_iso(),
                "Перезапуск после сбоя bridge.",
                JobStatus.RUNNING.value,
            ),
        )
        self._conn.commit()
        return int(cur.rowcount)

    def prune_old_jobs(self, days: int) -> int:
        cur = self._conn.execute(
            """
            DELETE FROM job_steps WHERE job_id IN (
                SELECT id FROM jobs
                WHERE updated_at < datetime('now', ?)
                AND status IN ('done', 'failed', 'canceled')
            )
            """,
            (f"-{days} days",),
        )
        steps = int(cur.rowcount)
        cur = self._conn.execute(
            """
            DELETE FROM jobs
            WHERE updated_at < datetime('now', ?)
            AND status IN ('done', 'failed', 'canceled')
            """,
            (f"-{days} days",),
        )
        self._conn.commit()
        return steps + int(cur.rowcount)

    def job_depth(self, job_id: str) -> int:
        depth = 0
        current = job_id
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            row = self._conn.execute(
                "SELECT parent_id FROM jobs WHERE id = ?",
                (current,),
            ).fetchone()
            if not row or not row[0]:
                break
            depth += 1
            current = str(row[0])
        return depth


_STORE: JobStore | None = None


def get_job_store() -> JobStore:
    global _STORE
    if _STORE is None:
        _STORE = JobStore()
    return _STORE


def reset_job_store_for_tests(path: Path | None = None) -> JobStore:
    global _STORE
    if _STORE is not None:
        _STORE.close()
    _STORE = JobStore(path=path)
    return _STORE
