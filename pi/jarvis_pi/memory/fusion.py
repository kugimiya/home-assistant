"""Reciprocal Rank Fusion for multi-channel search results."""

from __future__ import annotations

from jarvis_pi.memory.models import SearchHit


def rrf_fuse(
    ranked_lists: list[list[SearchHit]],
    *,
    k: int = 60,
    temporal_bonus: dict[str, float] | None = None,
) -> list[SearchHit]:
    """
    Merge ranked lists from independent channels using RRF.

    Each hit must have a unique ``id`` (e.g. fact:12, episode:3).
    """
    scores: dict[str, float] = {}
    best_hit: dict[str, SearchHit] = {}

    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            item_id = item.id
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            if item_id not in best_hit:
                best_hit[item_id] = item

    if temporal_bonus:
        for item_id, bonus in temporal_bonus.items():
            if item_id in scores:
                scores[item_id] += bonus

    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result: list[SearchHit] = []
    for item_id, score in ordered:
        hit = best_hit[item_id]
        result.append(
            SearchHit(
                id=hit.id,
                channel=hit.channel,
                text=hit.text,
                score=score,
                created_at=hit.created_at,
                extra=hit.extra,
            )
        )
    return result
