"""Pipeline foreground tools."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agent.catalog import enabled_tool_names, execute
from agent.pipeline.store import reset_job_store_for_tests


class PipelineToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["JOBS_DB_PATH"] = str(Path(self._tmp.name) / "jobs.db")
        reset_job_store_for_tests(Path(os.environ["JOBS_DB_PATH"]))
        self._saved_pipeline = os.environ.get("BRIDGE_PIPELINE")
        os.environ["BRIDGE_PIPELINE_STUB_WORKER"] = "1"

    def tearDown(self) -> None:
        if self._saved_pipeline is None:
            os.environ.pop("BRIDGE_PIPELINE", None)
        else:
            os.environ["BRIDGE_PIPELINE"] = self._saved_pipeline
        os.environ.pop("BRIDGE_PIPELINE_STUB_WORKER", None)
        os.environ.pop("JOBS_DB_PATH", None)
        self._tmp.cleanup()

    def test_pipeline_off(self) -> None:
        os.environ["BRIDGE_PIPELINE"] = "0"
        names = enabled_tool_names()
        self.assertNotIn("start_background_job", names)
        text, _ = execute(
            "start_background_job",
            '{"title":"t","brief":"b"}',
        )
        self.assertIn("выключены", text.lower())

    def test_start_job_when_on(self) -> None:
        os.environ["BRIDGE_PIPELINE"] = "1"
        self.assertIn("start_background_job", enabled_tool_names())
        text, _ = execute(
            "start_background_job",
            '{"title":"Test","brief":"do work","prompt":"user said"}',
        )
        self.assertIn("id=", text)


if __name__ == "__main__":
    unittest.main()
