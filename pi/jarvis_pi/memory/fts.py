"""FTS5 search with BM25 and confidence boosting; JSONL fallback."""

from __future__ import annotations

import re
import sqlite3

from jarvis_pi.memory.config import MemoryConfig
from jarvis_pi.memory.models import SearchHit
from jarvis_pi.memory.temporal import TemporalLayer, layer_sql_filter

_CONFIDENCE_MULT = {
    "EXTRACTED": 1.0,
    "INFERRED": 0.75,
    "AMBIGUOUS": 0.4,
}


def escape_fts_query(query: str) -> str:
    """Build OR-joined quoted tokens for MATCH."""
    tokens = re.findall(r"\w+", query.lower(), flags=re.UNICODE)
    if not tokens:
        return '""'
    parts = []
    for tok in tokens:
        safe = tok.replace('"', '""')
        parts.append(f'"{safe}"')
    return " OR ".join(parts)


def _confidence_case_sql() -> str:
    return """
    CASE f.confidence
        WHEN 'EXTRACTED' THEN 1.0
        WHEN 'INFERRED' THEN 0.75
        WHEN 'AMBIGUOUS' THEN 0.4
        ELSE 0.9
    END
    """


def search_facts(
    conn: sqlite3.Connection,
    query: str,
    *,
    config: MemoryConfig,
    layer: TemporalLayer = "all",
    limit: int = 10,
    fts_enabled: bool = True,
) -> list[SearchHit]:
    if fts_enabled:
        return _search_facts_fts(conn, query, config=config, layer=layer, limit=limit)
    return _search_facts_fallback(conn, query, layer=layer, limit=limit, config=config)


def _search_facts_fts(
    conn: sqlite3.Connection,
    query: str,
    *,
    config: MemoryConfig,
    layer: TemporalLayer,
    limit: int,
) -> list[SearchHit]:
    match = escape_fts_query(query)
    layer_sql, layer_params = layer_sql_filter(
        layer, "f.created_at", hot_hours=config.hot_hours, warm_days=config.warm_days
    )
    w_text = config.bm25_fact_text_weight
    w_tags = config.bm25_tags_weight
    sql = f"""
        SELECT
            f.id,
            f.fact_text,
            f.confidence,
            f.created_at,
            bm25(facts_fts, ?, ?) * ({_confidence_case_sql()}) AS score
        FROM facts_fts
        JOIN facts f ON facts_fts.rowid = f.id
        WHERE facts_fts MATCH ?
        {layer_sql}
        ORDER BY score
        LIMIT ?
    """
    params: tuple[object, ...] = (w_text, w_tags, match, *layer_params, limit)
    rows = conn.execute(sql, params).fetchall()
    hits: list[SearchHit] = []
    for row in rows:
        hits.append(
            SearchHit(
                id=f"fact:{row['id']}",
                channel="fact",
                text=str(row["fact_text"]),
                score=float(row["score"]) if row["score"] is not None else 0.0,
                created_at=str(row["created_at"]) if row["created_at"] else None,
                extra={"confidence": row["confidence"]},
            )
        )
    return hits


def search_episodes(
    conn: sqlite3.Connection,
    query: str,
    *,
    config: MemoryConfig,
    layer: TemporalLayer = "all",
    limit: int = 10,
    fts_enabled: bool = True,
) -> list[SearchHit]:
    if fts_enabled:
        return _search_episodes_fts(conn, query, config=config, layer=layer, limit=limit)
    return _search_episodes_fallback(conn, query, layer=layer, limit=limit, config=config)


def _search_episodes_fts(
    conn: sqlite3.Connection,
    query: str,
    *,
    config: MemoryConfig,
    layer: TemporalLayer,
    limit: int,
) -> list[SearchHit]:
    match = escape_fts_query(query)
    layer_sql, layer_params = layer_sql_filter(
        layer, "e.created_at", hot_hours=config.hot_hours, warm_days=config.warm_days
    )
    sql = f"""
        SELECT
            e.id,
            e.summary,
            e.importance,
            e.created_at,
            bm25(episodes_fts, 3.0, 1.0) AS score
        FROM episodes_fts
        JOIN episodes e ON episodes_fts.rowid = e.id
        WHERE episodes_fts MATCH ?
        {layer_sql}
        ORDER BY score
        LIMIT ?
    """
    params: tuple[object, ...] = (match, *layer_params, limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        SearchHit(
            id=f"episode:{row['id']}",
            channel="episode",
            text=str(row["summary"]),
            score=float(row["score"]) if row["score"] is not None else 0.0,
            created_at=str(row["created_at"]) if row["created_at"] else None,
            extra={"importance": row["importance"]},
        )
        for row in rows
    ]


def search_traits(
    conn: sqlite3.Connection,
    query: str,
    *,
    config: MemoryConfig,
    layer: TemporalLayer = "all",
    limit: int = 10,
    fts_enabled: bool = True,
) -> list[SearchHit]:
    if fts_enabled:
        return _search_traits_fts(conn, query, config=config, layer=layer, limit=limit)
    return _search_traits_fallback(conn, query, limit=limit)


def _search_traits_fts(
    conn: sqlite3.Connection,
    query: str,
    *,
    config: MemoryConfig,
    layer: TemporalLayer,
    limit: int,
) -> list[SearchHit]:
    match = escape_fts_query(query)
    layer_sql, layer_params = layer_sql_filter(
        layer, "t.last_updated", hot_hours=config.hot_hours, warm_days=config.warm_days
    )
    sql = f"""
        SELECT
            t.id,
            t.trait,
            t.value,
            t.confidence,
            t.last_updated,
            bm25(user_traits_fts, 2.0, 2.0) AS score
        FROM user_traits_fts
        JOIN user_traits t ON user_traits_fts.rowid = t.id
        WHERE user_traits_fts MATCH ?
        {layer_sql}
        ORDER BY score
        LIMIT ?
    """
    params: tuple[object, ...] = (match, *layer_params, limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        SearchHit(
            id=f"trait:{row['id']}",
            channel="trait",
            text=f"{row['trait']}: {row['value']}",
            score=float(row["score"]) if row["score"] is not None else 0.0,
            created_at=str(row["last_updated"]) if row["last_updated"] else None,
            extra={"confidence": row["confidence"]},
        )
        for row in rows
    ]


def _token_overlap(query: str, text: str) -> float:
    q = set(re.findall(r"\w+", query.lower(), flags=re.UNICODE))
    t = set(re.findall(r"\w+", text.lower(), flags=re.UNICODE))
    if not q:
        return 0.0
    return len(q & t) / len(q)


def _search_facts_fallback(
    conn: sqlite3.Connection,
    query: str,
    *,
    layer: TemporalLayer,
    limit: int,
    config: MemoryConfig,
) -> list[SearchHit]:
    layer_sql, layer_params = layer_sql_filter(
        layer, "created_at", hot_hours=config.hot_hours, warm_days=config.warm_days
    )
    sql = f"SELECT id, fact_text, confidence, created_at FROM facts WHERE 1=1 {layer_sql}"
    rows = conn.execute(sql, layer_params).fetchall()
    scored: list[tuple[float, SearchHit]] = []
    for row in rows:
        overlap = _token_overlap(query, str(row["fact_text"]))
        conf = _CONFIDENCE_MULT.get(str(row["confidence"]), 0.9)
        scored.append(
            (
                overlap * conf,
                SearchHit(
                    id=f"fact:{row['id']}",
                    channel="fact",
                    text=str(row["fact_text"]),
                    score=overlap * conf,
                    created_at=str(row["created_at"]) if row["created_at"] else None,
                    extra={"confidence": row["confidence"]},
                ),
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored[:limit]]


def _search_episodes_fallback(
    conn: sqlite3.Connection,
    query: str,
    *,
    layer: TemporalLayer,
    limit: int,
    config: MemoryConfig,
) -> list[SearchHit]:
    layer_sql, layer_params = layer_sql_filter(
        layer, "created_at", hot_hours=config.hot_hours, warm_days=config.warm_days
    )
    sql = f"SELECT id, summary, importance, created_at FROM episodes WHERE 1=1 {layer_sql}"
    rows = conn.execute(sql, layer_params).fetchall()
    scored: list[tuple[float, SearchHit]] = []
    for row in rows:
        overlap = _token_overlap(query, str(row["summary"]))
        scored.append(
            (
                overlap,
                SearchHit(
                    id=f"episode:{row['id']}",
                    channel="episode",
                    text=str(row["summary"]),
                    score=overlap,
                    created_at=str(row["created_at"]) if row["created_at"] else None,
                    extra={"importance": row["importance"]},
                ),
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored[:limit]]


def _search_traits_fallback(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
) -> list[SearchHit]:
    rows = conn.execute("SELECT id, trait, value, confidence, last_updated FROM user_traits").fetchall()
    scored: list[tuple[float, SearchHit]] = []
    for row in rows:
        text = f"{row['trait']}: {row['value']}"
        overlap = _token_overlap(query, text)
        scored.append(
            (
                overlap,
                SearchHit(
                    id=f"trait:{row['id']}",
                    channel="trait",
                    text=text,
                    score=overlap,
                    created_at=str(row["last_updated"]) if row["last_updated"] else None,
                    extra={"confidence": row["confidence"]},
                ),
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored[:limit]]
