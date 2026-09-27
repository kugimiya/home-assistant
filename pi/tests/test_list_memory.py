from unittest.mock import patch

from jarvis_pi.memory.tools import execute_memory_tool


def test_list_memory_tool_reports_facts_and_episodes(manager) -> None:
    mgr = manager
    mgr.ensure_session()
    mgr.add_fact("любит кофе без сахара", confidence="EXTRACTED")
    session_id = mgr._session_id
    assert session_id
    from jarvis_pi.memory.models import SessionSummaryResult

    mgr._persist_summary(
        session_id,
        SessionSummaryResult(
            summary="Обсуждали напитки.",
            tags=["кофе"],
            importance=50,
        ),
    )
    with patch("jarvis_pi.memory.tools.get_memory_manager", return_value=mgr):
        out = execute_memory_tool("list_memory", {"facts_limit": 5, "episodes_limit": 5})
    assert "фактов" in out.lower() or "Фактов" in out
    assert "кофе" in out
    assert "напитки" in out.lower() or "Напитки" in out


def test_list_memory_empty(manager) -> None:
    with patch("jarvis_pi.memory.tools.get_memory_manager", return_value=manager):
        out = execute_memory_tool("list_memory", {})
    assert "нет" in out.lower()
