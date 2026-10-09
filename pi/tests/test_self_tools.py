"""Self rewrite, self reset, and memory CRUD."""

from __future__ import annotations

import os

from unittest.mock import patch

from jarvis_pi.memory.tools import execute_memory_crud
from jarvis_pi.personality.overlay import load_overlay
from jarvis_pi.personality.state import load_trust
from jarvis_pi.personality.tools import execute_self_tool


def test_rewrite_and_reset_keep_memory(manager, tmp_path, monkeypatch) -> None:
    overlay = tmp_path / "self_overlay.json"
    personality = tmp_path / "personality.json"
    monkeypatch.setenv("PERSONALITY_OVERLAY_PATH", str(overlay))
    monkeypatch.setenv("PERSONALITY_PATH", str(personality))

    fact_id = manager.add_fact("любит чёрный кофе", source="user_explicit", confidence="EXTRACTED")
    reply = execute_self_tool(
        "rewrite_self",
        {"character": "говорю шёпотом и только загадками", "warmth": 0.9, "trust": 0.4},
    )
    assert "Самоправка записана" in reply
    saved = load_overlay(overlay)
    assert "загадками" in saved.character
    assert saved.warmth == 0.9
    assert load_trust(personality) == 0.4

    reset = execute_self_tool("reset_self", {})
    assert "Память на месте" in reset
    assert not overlay.exists()
    assert load_trust(personality) == 0.0
    assert manager.get_fact(fact_id) is not None
    os.environ.pop("PERSONALITY_OVERLAY_PATH", None)
    os.environ.pop("PERSONALITY_PATH", None)


def test_memory_crud_fact_and_trait(manager) -> None:
    with patch("jarvis_pi.memory.tools.get_memory_manager", return_value=manager):
        created = execute_memory_crud(
            {"entity": "fact", "action": "create", "text": "зовёт колонку по имени"}
        )
        assert "создан" in created
        fact_id = int(created.split("id=")[1].split(")")[0])
        updated = execute_memory_crud(
            {"entity": "fact", "action": "update", "id": fact_id, "text": "зовёт колонку Пи"}
        )
        assert "обновлён" in updated
        read_fact = execute_memory_crud({"entity": "fact", "action": "read", "id": fact_id})
        assert "Пи" in read_fact
        deleted = execute_memory_crud({"entity": "fact", "action": "delete", "id": fact_id})
        assert "удалён" in deleted
        missing = execute_memory_crud({"entity": "fact", "action": "read", "id": fact_id})
        assert "не найден" in missing

        trait = execute_memory_crud(
            {
                "entity": "trait",
                "action": "create",
                "trait": "кофе",
                "text": "без сахара",
                "confidence": "0.8",
            }
        )
        assert "создана" in trait
        read = execute_memory_crud({"entity": "trait", "action": "read", "trait": "кофе"})
        assert "без сахара" in read
        gone = execute_memory_crud({"entity": "trait", "action": "delete", "trait": "кофе"})
        assert "удалена" in gone
