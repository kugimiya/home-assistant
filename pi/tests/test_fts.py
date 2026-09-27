from jarvis_pi.memory import fts
from jarvis_pi.memory.config import MemoryConfig


def test_confidence_ordering_extracted_above_ambiguous(manager) -> None:
    mgr = manager
    mgr.add_fact("Пользователь любит кофе без сахара", confidence="EXTRACTED")
    mgr.add_fact("Возможно пользователь пьёт кофе с сахаром", confidence="AMBIGUOUS")
    hits = mgr.search("кофе", limit=5)
    fact_hits = [h for h in hits if h.channel == "fact"]
    assert len(fact_hits) >= 2
    extracted = next(h for h in fact_hits if "без сахара" in h.text)
    ambiguous = next(h for h in fact_hits if "с сахаром" in h.text)
    assert extracted.score >= ambiguous.score or fact_hits.index(extracted) < fact_hits.index(
        ambiguous
    )


def test_layer_hot_excludes_old_rows(manager) -> None:
    mgr = manager
    with mgr._lock:
        with mgr._conn:
            mgr._conn.execute(
                """
                INSERT INTO facts (fact_text, fact_norm, source, confidence, created_at)
                VALUES ('старый факт про чай', 'старый факт про чай', 'user_explicit', 'EXTRACTED',
                        datetime('now', '-10 hours'))
                """
            )
            mgr._conn.execute(
                "INSERT INTO facts_fts(facts_fts) VALUES('rebuild')"
            )
    mgr.add_fact("свежий факт про чай", confidence="EXTRACTED")
    hot = mgr.search("чай", layer="hot", limit=10)
    assert all("свежий" in h.text for h in hot if h.channel == "fact")
    cold_only = [h for h in hot if h.channel == "fact" and "старый" in h.text]
    assert not cold_only


def test_escape_fts_query_or_join() -> None:
    q = fts.escape_fts_query("кофе барсик")
    assert " OR " in q
    assert '"кофе"' in q


def test_escape_fts_query_empty() -> None:
    assert fts.escape_fts_query("   !!!") == '""'


def test_search_episodes_and_traits_channels(manager) -> None:
    mgr = manager
    with mgr._lock:
        with mgr._conn:
            mgr._conn.execute(
                """
                INSERT INTO episodes (summary, tags, importance)
                VALUES ('обсуждали погоду и прогулку', '["погода"]', 60)
                """
            )
            mgr._conn.execute("INSERT INTO episodes_fts(episodes_fts) VALUES('rebuild')")
            mgr._upsert_trait_row("любимый_напиток", "чай", 0.9, conn=mgr._conn, write_log=False)
            mgr._conn.execute("INSERT INTO user_traits_fts(user_traits_fts) VALUES('rebuild')")
    hits = mgr.search("погода чай", limit=10)
    channels = {h.channel for h in hits}
    assert "episode" in channels or "trait" in channels


def test_fallback_search_when_fts_disabled(manager, memory_config: MemoryConfig) -> None:
    mgr = manager
    mgr.add_fact("любимый напиток — какао", confidence="EXTRACTED")
    hits = fts.search_facts(
        mgr._conn,
        "какао",
        config=memory_config,
        fts_enabled=False,
        limit=5,
    )
    assert len(hits) == 1
    assert hits[0].id.startswith("fact:")
