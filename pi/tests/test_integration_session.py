from jarvis_pi.memory.models import ExtractedFact, SessionSummaryResult
from jarvis_pi.memory.manager import MemoryManager


def test_session_end_persists_facts_and_search(manager: MemoryManager) -> None:
    mgr = manager
    mgr.ensure_session()
    mgr.record_exchange("Запомни, я люблю кофе без сахара", "Хорошо, запомню.")
    summary = SessionSummaryResult(
        summary="Пользователь рассказал о предпочтениях в кофе.",
        tags=["кофе", "предпочтения"],
        importance=80,
        extracted_facts=[
            ExtractedFact(fact="Пользователь любит кофе без сахара", confidence="EXTRACTED"),
        ],
        traits=[],
    )
    session_id = mgr._session_id
    assert session_id
    mgr._persist_summary(session_id, summary)

    hits = mgr.search("кофе", limit=5)
    texts = " ".join(h.text for h in hits)
    assert "без сахара" in texts
    episodes = mgr.get_recent_episodes(limit=1)
    assert episodes and "кофе" in episodes[0]["summary"].lower()
