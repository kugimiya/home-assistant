"""Run Python written by the model. The result goes back to the model, not to speech."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_MAX_OUTPUT_CHARS = 4096
TIMEOUT_SEC = 15
_SECRET_PARTS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY")


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        upper = key.upper()
        if any(part in upper for part in _SECRET_PARTS):
            env.pop(key, None)
    return env


def run_python(code: str, *, timeout_sec: int | None = None) -> str:
    code = code.strip()
    if not code:
        return "Ошибка: пустой код."

    timeout = TIMEOUT_SEC if timeout_sec is None else max(1, int(timeout_sec))

    try:
        with tempfile.TemporaryDirectory(prefix="bridge-py-") as work:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                cwd=work,
                env=_child_env(),
            )
    except subprocess.TimeoutExpired:
        return f"Ошибка: выполнение дольше {timeout} секунд."
    except OSError as exc:
        return f"Ошибка запуска Python: {exc}"

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if completed.returncode != 0:
        parts = [f"Ошибка выполнения (код {completed.returncode})."]
        if stderr:
            parts.append(stderr[:_MAX_OUTPUT_CHARS])
        elif stdout:
            parts.append(stdout[:_MAX_OUTPUT_CHARS])
        return " ".join(parts)

    if not stdout:
        return "Код выполнен, но ничего не напечатано. Используй print() для результата."

    if len(stdout) > _MAX_OUTPUT_CHARS:
        return stdout[:_MAX_OUTPUT_CHARS] + "…"
    return stdout
