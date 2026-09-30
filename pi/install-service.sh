#!/usr/bin/env bash
# Register jarvis-pi as a user systemd unit (boot + restart on failure).
set -euo pipefail

PI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_NAME="jarvis-pi.service"
USER_UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_PATH="${USER_UNIT_DIR}/${UNIT_NAME}"
SET_AUDIO="${PI_DIR}/set-usb-audio.sh"
PYTHON="${PI_DIR}/.venv/bin/python"

usage() {
  echo "Usage: $0 [--uninstall]"
  exit "${1:-0}"
}

uninstall=false
if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall=true
elif [[ -n "${1:-}" ]]; then
  usage 1
fi

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

if [[ "$uninstall" == true ]]; then
  systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
  rm -f "$UNIT_PATH"
  systemctl --user daemon-reload
  echo "Removed user unit $UNIT_NAME (linger left enabled)."
  exit 0
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing venv: $PYTHON — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
if [[ ! -f "${PI_DIR}/.env" ]]; then
  echo "Missing ${PI_DIR}/.env — copy from .env.example and set WINDOWS_HOST" >&2
  exit 1
fi
if [[ ! -f "$SET_AUDIO" ]]; then
  echo "Missing $SET_AUDIO" >&2
  exit 1
fi
chmod +x "$SET_AUDIO"

mkdir -p "$USER_UNIT_DIR"

cat >"$UNIT_PATH" <<EOF
[Unit]
Description=Jarvis Pi edge service
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${PI_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStartPre=${SET_AUDIO}
ExecStart=${PYTHON} -m jarvis_pi
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=0

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_NAME"

if command -v loginctl >/dev/null 2>&1; then
  if ! loginctl show-user "$USER" -p Linger --value 2>/dev/null | grep -q yes; then
    echo "Enabling linger for $USER (requires sudo)..."
    sudo loginctl enable-linger "$USER"
  fi
fi

echo "Installed and started $UNIT_NAME"
echo "  status: systemctl --user status $UNIT_NAME"
echo "  logs:   journalctl --user -u $UNIT_NAME -f"
