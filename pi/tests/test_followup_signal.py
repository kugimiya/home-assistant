from jarvis_pi.commands.think import (
    _finalize_reply,
    _followup_from_markers,
    _implicit_await_followup,
    _strip_followup_markers,
)


def test_strip_followup_markers() -> None:
    assert _strip_followup_markers("Таймер на пять минут. [[DONE]]") == "Таймер на пять минут."


def test_followup_from_markers() -> None:
    assert _followup_from_markers("Уточни, пожалуйста. [[AWAIT_USER]]") is True
    assert _followup_from_markers("Готово. [[DONE]]") is False
    assert _followup_from_markers("Просто ответ.") is None


def test_implicit_await_followup_question() -> None:
    assert _implicit_await_followup("На сколько минут поставить таймер?") is True
    assert _implicit_await_followup("Таймер на пять минут поставлен.") is False


def test_finalize_reply_prefers_marker_over_question_heuristic() -> None:
    result = _finalize_reply("Ок. [[DONE]] А ещё вопрос?")
    assert result.await_followup is False
    assert "[[DONE]]" not in result.reply
