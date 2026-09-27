from jarvis_pi.memory.fusion import rrf_fuse
from jarvis_pi.memory.models import SearchHit


def test_rrf_merges_channels_with_prefixed_ids() -> None:
    facts = [
        SearchHit(id="fact:1", channel="fact", text="a"),
        SearchHit(id="fact:2", channel="fact", text="b"),
    ]
    episodes = [
        SearchHit(id="episode:1", channel="episode", text="c"),
    ]
    traits = [
        SearchHit(id="trait:1", channel="trait", text="d"),
    ]
    fused = rrf_fuse([facts, episodes, traits], k=60)
    ids = [h.id for h in fused]
    assert "fact:1" in ids
    assert "episode:1" in ids
    assert "trait:1" in ids
    assert fused[0].score >= fused[-1].score


def test_rrf_temporal_bonus() -> None:
    hits = [SearchHit(id="fact:1", channel="fact", text="a")]
    fused = rrf_fuse([hits], k=60, temporal_bonus={"fact:1": 0.05})
    assert fused[0].score > 1.0 / 61


def test_rrf_no_id_collision_between_tables() -> None:
    lists = [
        [SearchHit(id="fact:1", channel="fact", text="x")],
        [SearchHit(id="episode:1", channel="episode", text="y")],
    ]
    fused = rrf_fuse(lists, k=60)
    assert len(fused) == 2
    assert {h.id for h in fused} == {"fact:1", "episode:1"}
