"""Responses API event parsing."""

from __future__ import annotations

import json
import unittest

from agent.responses_llm import (
    final_response_from_events,
    function_calls_from_output,
    iter_response_events,
    output_items_from_response,
    text_from_output_items,
)


class ResponsesLlmTests(unittest.TestCase):
    def test_parse_stream(self) -> None:
        lines = [
            b'data: {"type":"response.output_text.delta","delta":"Hi"}\n',
            b'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n',
        ]
        events = iter_response_events(lines)
        self.assertEqual(len(events), 2)
        final = final_response_from_events(events)
        assert final is not None
        self.assertEqual(final.get("status"), "completed")

    def test_function_calls(self) -> None:
        payload = {
            "output": [
                {
                    "type": "function_call",
                    "name": "web_search",
                    "arguments": "{}",
                    "call_id": "c1",
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "done"}],
                },
            ]
        }
        items = output_items_from_response(payload)
        calls = function_calls_from_output(items)
        self.assertEqual(len(calls), 1)
        self.assertEqual(text_from_output_items(items), "done")


if __name__ == "__main__":
    unittest.main()
