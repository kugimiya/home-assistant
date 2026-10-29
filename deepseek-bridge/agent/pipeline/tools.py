"""Foreground pipeline tools (not available in background worker)."""

from __future__ import annotations

import json
from typing import Any

from agent.config import SPOKEN_CHAR_LIMIT
from agent.pipeline.config import job_max_depth, pipeline_enabled
from agent.pipeline.models import JobStatus
from agent.pipeline.store import get_job_store

FOREGROUND_TOOL_NAMES = frozenset(
    {
        "start_background_job",
        "list_background_jobs",
        "get_background_job_status",
        "get_background_job_result",
        "cancel_background_job",
    }
)

_PIPELINE_OFF = "Фоновые задачи выключены: BRIDGE_PIPELINE=0."

_last_started_job: tuple[str, str] | None = None


def consume_last_started_job() -> tuple[str, str] | None:
    global _last_started_job
    item = _last_started_job
    _last_started_job = None
    return item

FOREGROUND_SPECS: list[dict[str, object]] = [
    {
        "type": "function",
        "name": "start_background_job",
        "description": (
            "Запустить долгую фоновую задачу-агента: исследование, несколько поисков и Python. "
            "Сразу после вызова коротко скажи пользователю название задачи и что можно спросить статус позже."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Короткое название задачи для пользователя.",
                },
                "brief": {
                    "type": "string",
                    "description": "Инструкция агенту: что именно исследовать и в каком виде отчёт.",
                },
                "prompt": {
                    "type": "string",
                    "description": "Исходная формулировка пользователя; если пусто — используй контекст реплики.",
                },
                "parent_job_id": {
                    "type": "string",
                    "description": "Необязательно: id родительской задачи для подзадачи.",
                },
            },
            "required": ["title", "brief"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "list_background_jobs",
        "description": "Список недавних фоновых задач и их статусов.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Фильтр: queued, running, done, failed, canceled.",
                },
                "limit": {"type": "integer", "description": "Сколько задач вернуть (1–20)."},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_background_job_status",
        "description": (
            "Статус фоновой задачи по id или по части названия. "
            "Не выдумывай статус — только из этого инструмента."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "UUID задачи."},
                "title_query": {
                    "type": "string",
                    "description": "Часть названия, если id неизвестен.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_background_job_result",
        "description": (
            "Текст результата завершённой задачи. format=summary для озвучки, full — только для пересказа моделью."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "title_query": {"type": "string"},
                "format": {
                    "type": "string",
                    "enum": ["summary", "full"],
                    "description": "summary — коротко для голоса.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "cancel_background_job",
        "description": "Отменить фоновую задачу по id.",
        "parameters": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
]


def foreground_specs() -> list[dict[str, object]]:
    if not pipeline_enabled():
        return []
    return list(FOREGROUND_SPECS)


def _resolve_job(store: Any, job_id: str, title_query: str) -> Any:
    if job_id.strip():
        return store.get_job(job_id.strip())
    if title_query.strip():
        matches = store.find_by_title(title_query.strip(), limit=1)
        return matches[0] if matches else None
    return None


def _format_job_line(job: Any) -> str:
    parent = f" parent={job.parent_id[:8]}" if job.parent_id else ""
    note = f" — {job.progress_note}" if job.progress_note else ""
    return f"{job.id} «{job.title}» [{job.status.value}]{parent}{note}"


def execute_pipeline_tool(name: str, args: dict[str, object]) -> str:
    if not pipeline_enabled():
        return _PIPELINE_OFF
    store = get_job_store()
    if name == "start_background_job":
        title = str(args.get("title", "")).strip()
        brief = str(args.get("brief", "")).strip()
        prompt = str(args.get("prompt", "")).strip() or title
        parent_id = str(args.get("parent_job_id", "")).strip() or None
        if not title or not brief:
            return "Ошибка: нужны title и brief."
        if parent_id:
            parent = store.get_job(parent_id)
            if parent is None:
                return f"Ошибка: родительская задача {parent_id} не найдена."
            depth = store.job_depth(parent_id)
            if depth + 1 >= job_max_depth():
                return "Ошибка: превышена глубина подзадач."
        job = store.create_job(
            title=title,
            prompt=prompt,
            brief=brief,
            parent_id=parent_id,
        )
        from agent.pipeline.service import get_job_service

        global _last_started_job
        _last_started_job = (job.id, title)
        get_job_service().enqueue(job.id)
        return (
            f"Задача создана. id={job.id}. Название: {title}. "
            "Статус: queued. Спроси статус или результат позже."
        )
    if name == "list_background_jobs":
        status_raw = str(args.get("status", "")).strip().lower()
        status = None
        if status_raw:
            try:
                status = JobStatus(status_raw)
            except ValueError:
                return f"Ошибка: неизвестный статус {status_raw}."
        limit = args.get("limit", 10)
        try:
            lim = int(limit)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            lim = 10
        lim = max(1, min(20, lim))
        jobs = store.list_jobs(status=status, limit=lim)
        if not jobs:
            return "Фоновых задач не найдено."
        return "\n".join(_format_job_line(j) for j in jobs)
    if name == "get_background_job_status":
        job = _resolve_job(
            store,
            str(args.get("job_id", "")),
            str(args.get("title_query", "")),
        )
        if job is None:
            return "Задача не найдена."
        steps = store.list_steps(job.id)
        last = steps[-1].detail if steps else "нет шагов"
        return (
            f"id={job.id} «{job.title}» status={job.status.value} "
            f"api_calls={job.api_calls} tool_rounds={job.tool_rounds}. "
            f"progress={job.progress_note or '—'}. last_step={last}"
        )
    if name == "get_background_job_result":
        job = _resolve_job(
            store,
            str(args.get("job_id", "")),
            str(args.get("title_query", "")),
        )
        if job is None:
            return "Задача не найдена."
        if job.status not in (JobStatus.DONE, JobStatus.FAILED):
            return f"Результат ещё не готов. status={job.status.value}. progress={job.progress_note or '—'}"
        fmt = str(args.get("format", "summary")).strip().lower() or "summary"
        if job.status == JobStatus.FAILED:
            return job.error_text or job.progress_note or "Задача завершилась с ошибкой."
        if fmt == "full":
            return job.result_text or job.spoken_summary or "Пустой результат."
        text = job.spoken_summary or job.result_text or ""
        if len(text) > SPOKEN_CHAR_LIMIT:
            return text[: SPOKEN_CHAR_LIMIT - 1] + "…"
        return text or "Пустой результат."
    if name == "cancel_background_job":
        job_id = str(args.get("job_id", "")).strip()
        if not job_id:
            return "Ошибка: нужен job_id."
        if store.mark_canceled(job_id):
            return f"Задача {job_id} отменена."
        return f"Не удалось отменить {job_id} (не найдена или уже завершена)."
    return f"Неизвестный pipeline tool: {name}"


def is_pipeline_tool(name: str) -> bool:
    return name in FOREGROUND_TOOL_NAMES
