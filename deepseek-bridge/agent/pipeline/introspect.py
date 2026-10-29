"""API budget checkpoint: audit job history and decide next action."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

from agent.llm import assistant_message, post_chat
from agent.pipeline.models import Job
from agent.pipeline.store import JobStore


class IntrospectionVerdict(str, Enum):
    COMPLETE = "complete"
    STUCK = "stuck"
    CONTINUE = "continue"


@dataclass
class IntrospectionResult:
    verdict: IntrospectionVerdict
    summary: str
    rationale: str


_MAX_HISTORY_CHARS = 12000

_SYSTEM = (
    "Ты аудитор фоновой задачи колонки. По истории шагов реши исход. "
    "Ответь только JSON объектом без markdown: "
    '{"verdict":"complete"|"stuck"|"continue","summary":"...","rationale":"..."}. '
    "complete — задача по сути выполнена, summary = отчёт для пользователя. "
    "stuck — зацикливание или тупик, summary = что успели. "
    "continue — есть прогресс, но нужен ещё один сегмент работы."
)


def _serialize_history(
    job: Job,
    steps: list,
    request_input: list[dict[str, object]] | None,
) -> str:
    lines = [
        f"title={job.title}",
        f"prompt={job.prompt}",
        f"brief={job.brief}",
        f"status={job.status.value}",
        f"api_calls={job.api_calls}",
        f"tool_rounds={job.tool_rounds}",
    ]
    for step in steps:
        tool = step.tool_name or step.kind
        lines.append(f"step[{step.step_index}] {tool}: {step.detail}")
    if request_input:
        try:
            blob = json.dumps(request_input, ensure_ascii=False)
        except (TypeError, ValueError):
            blob = str(request_input)
        if len(blob) > _MAX_HISTORY_CHARS:
            blob = blob[-_MAX_HISTORY_CHARS:] + "… [история усечена]"
            lines.append("note=request_input truncated")
        lines.append(f"request_input={blob}")
    text = "\n".join(lines)
    if len(text) > _MAX_HISTORY_CHARS:
        return text[: _MAX_HISTORY_CHARS - 1] + "…"
    return text


def parse_introspection_content(content: str) -> IntrospectionResult | None:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[^{}]*\"verdict\"[^{}]*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    raw_verdict = str(data.get("verdict", "")).strip().lower()
    try:
        verdict = IntrospectionVerdict(raw_verdict)
    except ValueError:
        return None
    summary = str(data.get("summary", "")).strip()
    rationale = str(data.get("rationale", "")).strip()
    return IntrospectionResult(verdict=verdict, summary=summary, rationale=rationale)


def run_introspection(
    store: JobStore,
    job: Job,
    request_input: list[dict[str, object]] | None,
    *,
    retry: bool = True,
) -> IntrospectionResult:
    steps = store.list_steps(job.id)
    history = _serialize_history(job, steps, request_input)
    if not history.strip():
        return IntrospectionResult(
            verdict=IntrospectionVerdict.STUCK,
            summary="",
            rationale="Пустая история задачи.",
        )
    messages: list[dict[str, object]] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": history},
    ]
    for attempt in range(2 if retry else 1):
        payload, err = post_chat(messages, tools=None, temperature=0.2, max_tokens=800)
        if err is not None or payload is None:
            continue
        message = assistant_message(payload)
        if message is None:
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        parsed = parse_introspection_content(content)
        if parsed is not None:
            return parsed
    return IntrospectionResult(
        verdict=IntrospectionVerdict.STUCK,
        summary="",
        rationale="Не удалось разобрать ответ аудитора.",
    )
