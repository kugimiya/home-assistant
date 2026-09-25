"""Execute short Python snippets for calculations (tool output for the model)."""

from __future__ import annotations

import subprocess
import sys

_MAX_OUTPUT_CHARS = 4096
_TIMEOUT_SEC = 5


def run_python(code: str) -> str:
    code = code.strip()
    if not code:
        return "Ошибка: пустой код."

    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"Ошибка: выполнение дольше {_TIMEOUT_SEC} секунд."
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
