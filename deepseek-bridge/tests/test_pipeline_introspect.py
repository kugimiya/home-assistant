"""Introspection JSON parsing."""

from __future__ import annotations

import unittest

from agent.pipeline.introspect import IntrospectionVerdict, parse_introspection_content


class IntrospectParseTests(unittest.TestCase):
    def test_complete(self) -> None:
        raw = '{"verdict":"complete","summary":"ok","rationale":"done"}'
        result = parse_introspection_content(raw)
        assert result is not None
        self.assertEqual(result.verdict, IntrospectionVerdict.COMPLETE)
        self.assertEqual(result.summary, "ok")

    def test_stuck(self) -> None:
        raw = "```json\n{\"verdict\":\"stuck\",\"summary\":\"\",\"rationale\":\"loop\"}\n```"
        result = parse_introspection_content(raw)
        assert result is not None
        self.assertEqual(result.verdict, IntrospectionVerdict.STUCK)

    def test_continue(self) -> None:
        raw = '{"verdict":"continue","summary":"","rationale":"need more"}'
        result = parse_introspection_content(raw)
        assert result is not None
        self.assertEqual(result.verdict, IntrospectionVerdict.CONTINUE)


if __name__ == "__main__":
    unittest.main()
