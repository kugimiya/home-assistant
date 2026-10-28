"""Chat Completions client for the station. Uses the bridge token file."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request

from agent.config import CHAT_URL, MODEL_MAX_TOKENS, MODEL_TIMEOUT_SEC, load_token, model_name


def _ssl_context() -> ssl.SSLContext:
    cafile = os.environ.get("SSL_CERT_FILE")
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def post_chat(
    messages: list[dict[str, object]],
    *,
    tools: list[dict[str, object]] | None = None,
    temperature: float = 0.6,
    max_tokens: int = MODEL_MAX_TOKENS,
    timeout: float = MODEL_TIMEOUT_SEC,
) -> tuple[dict[str, object] | None, int | str | None]:
    try:
        token = load_token()
    except (OSError, RuntimeError) as exc:
        return None, type(exc).__name__

    body: dict[str, object] = {
        "model": model_name(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    request = urllib.request.Request(
        CHAT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return None, exc.code
    except Exception as exc:
        return None, type(exc).__name__
    if not isinstance(payload, dict):
        return None, "bad_response"
    return payload, None


def assistant_message(payload: dict[str, object]) -> dict[str, object] | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    return message
