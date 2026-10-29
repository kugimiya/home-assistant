"""Background job execution (stub and Responses agent)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from agent.config import SPOKEN_CHAR_LIMIT
from agent.pipeline.config import (
    job_api_calls_extension,
    job_max_api_calls,
    job_max_api_calls_total,
    job_max_introspections,
    job_max_tool_rounds,
    job_step_timeout_sec,
)
from agent.pipeline.instructions import build_worker_instructions
from agent.pipeline.introspect import IntrospectionVerdict, run_introspection
from agent.pipeline.models import Job, JobStatus
from agent.pipeline.store import get_job_store
from agent.pipeline.tools import FOREGROUND_TOOL_NAMES
from agent.responses_llm import (
    function_calls_from_output,
    job_model_name,
    output_items_from_response,
    post_responses,
)


def _log(msg: str) -> None:
    print(msg.replace("\n", " "), flush=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def job_tool_specs() -> list[dict[str, object]]:
    from agent.catalog import enabled_specs
    from agent.pipeline.config import job_tool_disabled

    skip = FOREGROUND_TOOL_NAMES | {"decline"}
    specs: list[dict[str, object]] = []
    for spec in enabled_specs():
        name = str(spec["name"])
        if name in skip or job_tool_disabled(name):
            continue
        specs.append(spec)
    return specs


def _spoken_summary(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= SPOKEN_CHAR_LIMIT:
        return cleaned
    return cleaned[: SPOKEN_CHAR_LIMIT - 1] + "…"


def run_job_stub(job_id: str) -> None:
    store = get_job_store()
    job = store.get_job(job_id)
    if job is None or store.is_canceled(job_id):
        return
    store.update_job(
        job_id,
        status=JobStatus.RUNNING,
        started_at=_now_iso(),
        progress_note="Stub worker: имитация работы.",
    )
    _log(f"job {job_id[-8:]} stub start")
    store.append_step(job_id, kind="note", detail="stub: начало")
    store.append_step(job_id, kind="tool", tool_name="web_search", detail="stub: поиск")
    result = (
        f"Stub-отчёт по задаче «{job.title}». "
        f"Исходный запрос: {job.prompt}. "
        "Реальный worker включится без BRIDGE_PIPELINE_STUB_WORKER."
    )
    store.update_job(
        job_id,
        status=JobStatus.DONE,
        finished_at=_now_iso(),
        result_text=result,
        spoken_summary=_spoken_summary(result),
        progress_note="Stub: готово.",
    )
    _log(f"job {job_id[-8:]} stub done")


def _budget_exceeded(job: Job) -> bool:
    if job.api_calls >= job.current_api_budget:
        return True
    if job.api_calls >= job_max_api_calls_total():
        return True
    return False


def _apply_introspection(
    job_id: str,
    job: Job,
    request_input: list[dict[str, object]],
) -> tuple[bool, list[dict[str, object]]]:
    """Returns (should_stop_worker, possibly_updated_input)."""
    store = get_job_store()
    store.update_job(
        job_id,
        introspection_count=job.introspection_count + 1,
    )
    store.increment_api_calls(job_id)
    job = store.get_job(job_id)
    assert job is not None
    result = run_introspection(store, job, request_input)
    store.append_step(
        job_id,
        kind="introspection",
        detail=f"{result.verdict.value}: {result.rationale}"[:500],
    )
    _log(f"job {job_id[-8:]} introspection {result.verdict.value}")

    if result.verdict == IntrospectionVerdict.COMPLETE:
        summary = result.summary or result.rationale or "Задача завершена по аудиту."
        store.update_job(
            job_id,
            status=JobStatus.DONE,
            finished_at=_now_iso(),
            result_text=summary,
            spoken_summary=_spoken_summary(summary),
            progress_note="Завершено по introspection.",
        )
        _on_job_done(job_id)
        return True, request_input

    if result.verdict == IntrospectionVerdict.STUCK:
        err = result.rationale or "Агент застрял или зациклился."
        partial = result.summary or ""
        store.update_job(
            job_id,
            status=JobStatus.FAILED,
            finished_at=_now_iso(),
            error_text=err,
            result_text=partial or None,
            spoken_summary=_spoken_summary(partial) if partial else None,
            progress_note=err,
        )
        _on_job_done(job_id)
        return True, request_input

    # continue
    job = store.get_job(job_id)
    assert job is not None
    if job.introspection_count >= job_max_introspections():
        store.update_job(
            job_id,
            status=JobStatus.FAILED,
            finished_at=_now_iso(),
            error_text="Исчерпан лимит introspection.",
            progress_note="Исчерпан лимит introspection.",
        )
        _on_job_done(job_id)
        return True, request_input
    if job.api_calls >= job_max_api_calls_total():
        store.update_job(
            job_id,
            status=JobStatus.FAILED,
            finished_at=_now_iso(),
            error_text="Исчерпан общий лимит API.",
            progress_note="Исчерпан общий лимит API.",
        )
        _on_job_done(job_id)
        return True, request_input

    extension = job_api_calls_extension()
    store.update_job(
        job_id,
        current_api_budget=job.current_api_budget + extension,
        budget_extensions=job.budget_extensions + 1,
        progress_note=f"Продолжаем после аудита: {result.rationale[:120]}",
    )
    if result.rationale:
        request_input = list(request_input)
        request_input.append(
            {
                "role": "user",
                "content": f"Аудитор: {result.rationale}. Продолжай задачу.",
            }
        )
    return False, request_input


def _on_job_done(job_id: str) -> None:
    store = get_job_store()
    job = store.get_job(job_id)
    if job is None:
        return
    _log(f"job {job_id[-8:]} finished status={job.status.value}")


def _execute_worker_tool(name: str, arguments_json: str) -> tuple[str, bool]:
    from agent import catalog

    if name == "run_python":
        try:
            args = json.loads(arguments_json or "{}")
        except json.JSONDecodeError:
            args = {}
        code = str(args.get("code", ""))
        from agent.pipeline.config import job_python_timeout_sec
        from agent.tools import python_runner

        return python_runner.run_python(code, timeout_sec=job_python_timeout_sec()), False
    return catalog.execute(name, arguments_json)


def run_job(job_id: str) -> None:
    store = get_job_store()
    job = store.get_job(job_id)
    if job is None or store.is_canceled(job_id):
        return

    store.update_job(
        job_id,
        status=JobStatus.RUNNING,
        started_at=job.started_at or _now_iso(),
        model=job_model_name(),
        progress_note="Worker запущен.",
    )
    if job.current_api_budget <= 0:
        store.update_job(job_id, current_api_budget=job_max_api_calls())

    request_input: list[dict[str, object]] = [
        {
            "role": "user",
            "content": f"{job.prompt}\n\nИнструкция:\n{job.brief}",
        }
    ]
    instructions = build_worker_instructions()
    tools = job_tool_specs()
    timeout = job_step_timeout_sec()
    max_rounds = job_max_tool_rounds()

    for round_idx in range(max_rounds + 1):
        job = store.get_job(job_id)
        if job is None or store.is_canceled(job_id):
            if job and job.status != JobStatus.CANCELED:
                store.mark_canceled(job_id)
            return

        if _budget_exceeded(job):
            if job.introspection_count >= job_max_introspections() and job.api_calls >= job_max_api_calls_total():
                store.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    finished_at=_now_iso(),
                    error_text="Исчерпан лимит API.",
                    progress_note="Исчерпан лимит API.",
                )
                _on_job_done(job_id)
                return
            stop, request_input = _apply_introspection(job_id, job, request_input)
            if stop:
                return
            continue

        err_code: int | str | None = None
        for attempt in range(3):
            final_response, full_text, has_calls, err_code = post_responses(
                request_input,
                instructions=instructions,
                tools=tools,
                timeout=timeout,
            )
            store.increment_api_calls(job_id)
            if err_code == 429:
                store.update_job(
                    job_id,
                    progress_note="Пауза: лимит API 429, повтор…",
                )
                time.sleep(2**attempt)
                continue
            break

        job = store.get_job(job_id)
        if job is None:
            return

        if err_code is not None:
            store.update_job(
                job_id,
                status=JobStatus.FAILED,
                finished_at=_now_iso(),
                error_text=f"DeepSeek error: {err_code}",
                progress_note=str(err_code),
            )
            _on_job_done(job_id)
            return

        if final_response and final_response.get("status") == "failed":
            err = final_response.get("error")
            message = "unknown"
            if isinstance(err, dict) and err.get("message"):
                message = str(err["message"])
            store.update_job(
                job_id,
                status=JobStatus.FAILED,
                finished_at=_now_iso(),
                error_text=message,
            )
            _on_job_done(job_id)
            return

        output_items = output_items_from_response(final_response)
        store.update_job(job_id, tool_rounds=job.tool_rounds + 1)

        if has_calls:
            request_input.extend(output_items)
            for call in function_calls_from_output(output_items):
                call_id = str(call.get("call_id") or call.get("id") or "").strip()
                name = str(call.get("name") or "").strip()
                arguments = str(call.get("arguments") or "{}")
                if not call_id or not name:
                    continue
                _log(f"job {job_id[-8:]} tool {name}")
                result, _ = _execute_worker_tool(name, arguments)
                store.append_step(
                    job_id,
                    kind="tool",
                    tool_name=name,
                    detail=result[:500],
                )
                store.update_job(
                    job_id,
                    progress_note=f"Шаг {round_idx + 1}: {name}",
                )
                request_input.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result,
                    }
                )
            if store.is_canceled(job_id):
                return
            continue

        if full_text.strip():
            store.update_job(
                job_id,
                status=JobStatus.DONE,
                finished_at=_now_iso(),
                result_text=full_text.strip(),
                spoken_summary=_spoken_summary(full_text),
                progress_note="Готово.",
            )
            _on_job_done(job_id)
            return

        if not output_items:
            break

    store.update_job(
        job_id,
        status=JobStatus.FAILED,
        finished_at=_now_iso(),
        error_text="Слишком много шагов или пустой ответ.",
        progress_note="Лимит раундов.",
    )
    _on_job_done(job_id)
