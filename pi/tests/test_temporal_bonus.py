from jarvis_pi.memory import fts
from jarvis_pi.memory.config import MemoryConfig
from jarvis_pi.memory.temporal import temporal_layer_bonus


def test_temporal_layer_bonus_values() -> None:
    assert temporal_layer_bonus("hot") == 0.02
    assert temporal_layer_bonus("warm") == 0.01
    assert temporal_layer_bonus("cold") == 0.0
    assert temporal_layer_bonus("all") == 0.0


def test_episodes_and_traits_fallback(memory_config: MemoryConfig, manager) -> None:
    mgr = manager
    with mgr._lock:
        with mgr._conn:
            mgr._conn.execute(
                "INSERT INTO episodes (summary, tags) VALUES ('прогулка в парке', '[]')"
            )
            mgr._conn.execute(
                """
                INSERT INTO user_traits (trait, value, confidence)
                VALUES ('хобби', 'бег', 0.8)
                """
            )
    episodes = fts.search_episodes(
        mgr._conn, "парк", config=memory_config, fts_enabled=False, limit=5
    )
    traits = fts.search_traits(mgr._conn, "бег", config=memory_config, fts_enabled=False, limit=5)
    assert episodes and episodes[0].channel == "episode"
    assert traits and traits[0].channel == "trait"
