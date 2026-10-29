"""Job service and stub worker."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from agent.pipeline.models import JobStatus
from agent.pipeline.service import JobService
from agent.pipeline.store import get_job_store, reset_job_store_for_tests


class PipelineServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["JOBS_DB_PATH"] = str(Path(self._tmp.name) / "jobs.db")
        os.environ["BRIDGE_PIPELINE"] = "1"
        os.environ["BRIDGE_PIPELINE_STUB_WORKER"] = "1"
        reset_job_store_for_tests(Path(os.environ["JOBS_DB_PATH"]))
        import agent.pipeline.service as svc_mod

        svc_mod._SERVICE = None
        self.service = JobService()

    def tearDown(self) -> None:
        os.environ.pop("BRIDGE_PIPELINE", None)
        os.environ.pop("BRIDGE_PIPELINE_STUB_WORKER", None)
        os.environ.pop("JOBS_DB_PATH", None)
        self._tmp.cleanup()

    def test_stub_worker_completes(self) -> None:
        store = get_job_store()
        job = store.create_job(title="T", prompt="p", brief="b")
        self.service.ensure_started()
        self.service.enqueue(job.id)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            loaded = store.get_job(job.id)
            assert loaded is not None
            if loaded.status == JobStatus.DONE:
                break
            time.sleep(0.05)
        loaded = store.get_job(job.id)
        assert loaded is not None
        self.assertEqual(loaded.status, JobStatus.DONE)
        self.assertTrue(loaded.result_text)


if __name__ == "__main__":
    unittest.main()
