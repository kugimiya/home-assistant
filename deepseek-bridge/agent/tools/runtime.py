"""Where the bridge runs: Yandex, DeepSeek, and the station itself."""

from __future__ import annotations

from agent.config import (
    CHAT_URL,
    DEFAULT_MODEL,
    MAX_TOOL_ROUNDS,
    MODEL_MAX_TOKENS,
    MODEL_TIMEOUT_SEC,
    SPOKEN_CHAR_LIMIT,
    STATION_TOOLS,
    model_name,
    tool_enabled,
)
from agent.tools.python_runner import TIMEOUT_SEC


def describe_runtime() -> str:
    from agent.catalog import enabled_specs

    model = model_name()
    parts = [
        "Как устроен ответ колонки. ",
        "Яндекс, серверы uniproxy.alice.yandex.net. "
        "Микрофон, распознавание речи и wake-фраза остаются у Яндекса. "
        "Озвучка тоже: звук приходит из синтеза Яндекса. "
        "Музыку, радио, громкость, таймер, будильник, паузу, следующий и предыдущий трек "
        "и bluetooth выполняет Яндекс. Такие фразы bridge отдаёт ему целиком, "
        "DeepSeek их не видит. ",
        f"DeepSeek, сервер {CHAT_URL}, модель {model}"
        + ("" if model == DEFAULT_MODEL else f", по умолчанию {DEFAULT_MODEL}")
        + ". "
        "Туда уходит только текст реплики и результаты локальных инструментов. "
        "Аудио туда не отправляется, голос оттуда не приходит. "
        "Модель не выполняет инструменты у себя: она называет имя и аргументы, "
        "код крутится на колонке, текст результата возвращается в следующий запрос. "
        f"Один ход: не больше {MODEL_MAX_TOKENS} токенов и {MODEL_TIMEOUT_SEC} секунд, "
        f"инструментов не больше {MAX_TOOL_ROUNDS} раундов. "
        f"Вслух уходит не больше {SPOKEN_CHAR_LIMIT} символов. "
        "Краткое саммари памяти пишется тем же запросом к DeepSeek. ",
        "Локально на колонке работает процесс bridge. "
        "Он стоит между прошивкой колонки и Яндексом, слушает порт 8443. "
        "В режиме hybrid голосовой запрос удерживается, пока bridge не решит. "
        "Пустой текст и команды музыки и плеера уходят в Яндекс. "
        "Остальное bridge забирает: отменяет ответ Яндекса, спрашивает DeepSeek, "
        "отдаёт колонке текст и просит у Яндекса озвучку. "
        "Память и характер лежат в файлах на колонке. "
        "Погода запрашивается с колонки у wttr.in. "
        "Поиск запрашивается с колонки у DuckDuckGo. "
        "Умный дом запрашивается с колонки у Home Assistant, "
        "адрес берётся из окружения процесса. "
        "Python-код модели запускается на колонке отдельным процессом интерпретатора, "
        f"не дольше {TIMEOUT_SEC} секунд. Результат — то, что код напечатал через print. ",
        "Сейчас модели доступны такие локальные инструменты. ",
    ]
    for spec in enabled_specs():
        name = str(spec["name"])
        description = " ".join(str(spec["description"]).split())
        parts.append(f"{name}: {description} ")
    disabled = [name for name in STATION_TOOLS if not tool_enabled(name)]
    if disabled:
        listed = ", ".join(disabled)
        parts.append(
            f"Сейчас выключены и остаются у Яндекса: {listed}. "
            "Даже если их включить, фразы про музыку, таймер и громкость "
            "всё равно уходят в Яндекс раньше, чем их увидит модель. "
        )
    try:
        from agent.pipeline.config import max_concurrent_jobs, pipeline_enabled
        from agent.responses_llm import job_model_name, responses_url

        if pipeline_enabled():
            parts.append(
                "Фоновый agent pipeline включён (BRIDGE_PIPELINE=1). "
                "Долгие задачи идут в jobs.db, worker ходит в Responses API "
                f"{responses_url()}, модель {job_model_name()}. "
                f"Одновременно не больше {max_concurrent_jobs()} job. "
                "Голосовой ответ по-прежнему через Chat Completions и короткие лимиты. "
                "Есть лимит API-вызовов на job и introspection при отсечке. "
            )
    except Exception:
        pass
    return "".join(parts)
