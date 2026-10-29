"""Tests for job store."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agent.pipeline.models import JobStatus
from agent.pipeline.store import JobStore, reset_job_store_for_tests


class PipelineStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db = Path(self._tmp.name) / "jobs.db"
        os.environ["JOBS_DB_PATH"] = str(self._db)
        self.store = reset_job_store_for_tests(self._db)

    def tearDown(self) -> None:
        os.environ.pop("JOBS_DB_PATH", None)
        self._tmp.cleanup()

    def test_create_and_status_flow(self) -> None:
        job = self.store.create_job(
            title="Зарплаты",
            prompt="изучи зарплаты",
            brief="собери таблицу",
        )
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.store.update_job(job.id, status=JobStatus.RUNNING, started_at="t0")
        self.store.append_step(job.id, kind="tool", tool_name="web_search", detail="query ok")
        self.store.update_job(
            job.id,
            status=JobStatus.DONE,
            result_text="итог",
            spoken_summary="кратко",
        )
        loaded = self.store.get_job(job.id)
        assert loaded is not None
        self.assertEqual(loaded.status, JobStatus.DONE)
        steps = self.store.list_steps(job.id)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].tool_name, "web_search")

    def test_cancel_and_api_calls(self) -> None:
        job = self.store.create_job(title="t", prompt="p", brief="b")
        calls = self.store.increment_api_calls(job.id, 2)
        self.assertEqual(calls, 2)
        self.store.mark_canceled(job.id)
        self.assertTrue(self.store.is_canceled(job.id))

    def test_find_by_title(self) -> None:
        self.store.create_job(title="Зарплаты программистов", prompt="p", brief="b")
        found = self.store.find_by_title("программист")
        self.assertEqual(len(found), 1)

    def test_requeue_running(self) -> None:
        job = self.store.create_job(title="t", prompt="p", brief="b")
        self.store.update_job(job.id, status=JobStatus.RUNNING)
        n = self.store.requeue_running_jobs()
        self.assertEqual(n, 1)
        loaded = self.store.get_job(job.id)
        assert loaded is not None
        self.assertEqual(loaded.status, JobStatus.QUEUED)


if __name__ == "__main__":
    unittest.main()
