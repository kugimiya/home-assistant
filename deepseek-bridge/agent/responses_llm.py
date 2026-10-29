"""DeepSeek Responses API client for background jobs."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from collections.abc import Iterable

from agent.config import load_token

DEFAULT_RESPONSES_URL = "https://api.deepseek.com/responses"
DEFAULT_JOB_MODEL = "deepseek-chat"


def responses_url() -> str:
    return os.getenv("BRIDGE_RESPONSES_URL", DEFAULT_RESPONSES_URL).strip() or DEFAULT_RESPONSES_URL


def job_model_name() -> str:
    return os.getenv("BRIDGE_JOB_MODEL", DEFAULT_JOB_MODEL).strip() or DEFAULT_JOB_MODEL


def _ssl_context() -> ssl.SSLContext:
    cafile = os.environ.get("SSL_CERT_FILE")
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def reasoning_body() -> dict[str, str]:
    from agent.config import env_flag

    if not env_flag("BRIDGE_JOB_REASONING", False):
        return {"effort": "none"}
    effort = os.getenv("BRIDGE_JOB_REASONING_EFFORT", "low").strip().lower() or "low"
    allowed = {"low", "high", "max", "minimal", "medium", "xhigh"}
    if effort not in allowed:
        effort = "low"
    return {"effort": effort}


def iter_response_events(raw_lines: Iterable[bytes]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for raw_line in raw_lines:
        line = raw_line.decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def output_text_delta(event: dict[str, object]) -> str:
    if event.get("type") != "response.output_text.delta":
        return ""
    delta = event.get("delta")
    return delta if isinstance(delta, str) else ""


def final_response_from_events(events: list[dict[str, object]]) -> dict[str, object] | None:
    for event in reversed(events):
        event_type = event.get("type")
        if event_type in ("response.completed", "response.incomplete", "response.failed"):
            response = event.get("response")
            if isinstance(response, dict):
                return response
    return None


def output_items_from_response(response: dict[str, object] | None) -> list[dict[str, object]]:
    if not response:
        return []
    output_raw = response.get("output")
    output_items: list[dict[str, object]] = []
    if isinstance(output_raw, list):
        for item in output_raw:
            if isinstance(item, dict):
                output_items.append(item)
    return output_items


def text_from_output_items(output_items: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for item in output_items:
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "output_text":
                text = str(part.get("text", ""))
                if text:
                    parts.append(text)
    return "".join(parts).strip()


def function_calls_from_output(output_items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [item for item in output_items if item.get("type") == "function_call"]


PostResponsesResult = tuple[dict[str, object] | None, str, bool, int | str | None]


def post_responses(
    request_input: list[dict[str, object]],
    *,
    instructions: str,
    tools: list[dict[str, object]],
    timeout: float,
    model: str | None = None,
) -> PostResponsesResult:
    try:
        token = load_token()
    except (OSError, RuntimeError) as exc:
        return None, "", False, type(exc).__name__

    body: dict[str, object] = {
        "model": model or job_model_name(),
        "instructions": instructions,
        "input": request_input,
        "stream": True,
        "tool_choice": "auto",
        "tools": tools,
        "reasoning": reasoning_body(),
    }
    request = urllib.request.Request(
        responses_url(),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            events = iter_response_events(response)
            chunks: list[str] = []
            for event in events:
                piece = output_text_delta(event)
                if piece:
                    chunks.append(piece)
            final_response = final_response_from_events(events)
            output_items = output_items_from_response(final_response)
            has_function_calls = bool(function_calls_from_output(output_items))
            full_text = "".join(chunks).strip() or text_from_output_items(output_items)
            return final_response, full_text, has_function_calls, None
    except urllib.error.HTTPError as exc:
        return None, "", False, exc.code
    except Exception as exc:
        return None, "", False, type(exc).__name__
