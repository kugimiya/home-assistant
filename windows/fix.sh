#!/usr/bin/env bash
# Git Bash wrapper: runs fix.ps1 (no Python reinstall).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$ROOT/fix.ps1"
