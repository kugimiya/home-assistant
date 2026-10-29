"""Worker tool set and budget helpers."""

from __future__ import annotations

import os
import unittest

from agent.pipeline.tools import FOREGROUND_TOOL_NAMES
from agent.pipeline.worker import job_tool_specs


class PipelineWorkerTests(unittest.TestCase):
    def test_job_tools_exclude_pipeline_and_decline(self) -> None:
        os.environ.pop("BRIDGE_PIPELINE", None)
        names = {str(s["name"]) for s in job_tool_specs()}
        self.assertTrue(names.isdisjoint(FOREGROUND_TOOL_NAMES))
        self.assertNotIn("decline", names)


if __name__ == "__main__":
    unittest.main()
