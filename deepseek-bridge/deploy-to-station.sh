#!/usr/bin/env bash
set -euo pipefail

CREDS="${HOME}/.ssh/yandex-station.env"
if [ -f "$CREDS" ]; then
  # shellcheck disable=SC1090
  . "$CREDS"
fi
STATION_HOST="${STATION_HOST:-192.168.1.111}"
STATION_USER="${STATION_USER:-root}"
STATION="${STATION_USER}@${STATION_HOST}"
REMOTE_DIR="/data/quasar/deepseek-bridge"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/deepseek-bridge"
ARCHIVE="$(mktemp -t bridge-deploy.XXXXXX.tgz)"
trap 'rm -f "$ARCHIVE"' EXIT

tar -C "$SRC" -czf "$ARCHIVE" \
  --exclude=token \
  --exclude=./data \
  --exclude=bridge.log \
  --exclude=bridge.pid \
  --exclude=__pycache__ \
  --exclude=.venv \
  .

ssh_with_auth() {
  local remote_cmd="$1"
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "$STATION" "true" 2>/dev/null; then
    ssh -o StrictHostKeyChecking=accept-new "$STATION" "$remote_cmd"
    return
  fi
  if [ -z "${STATION_PASSWORD:-}" ]; then
    echo "No SSH key and no STATION_PASSWORD in $CREDS" >&2
    exit 1
  fi
  expect <<EOF
set timeout 120
log_user 1
spawn ssh -o StrictHostKeyChecking=accept-new ${STATION_USER}@${STATION_HOST} ${remote_cmd}
expect {
  -re "(?i)password:" { send "${STATION_PASSWORD}\r"; exp_continue }
  eof
}
catch wait result
exit [lindex \$result 3]
EOF
}

upload_archive() {
  local remote_path="$1"
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "$STATION" "true" 2>/dev/null; then
    cat "$ARCHIVE" | ssh -o StrictHostKeyChecking=accept-new "$STATION" "cat > ${remote_path}"
    return
  fi
  if [ -z "${STATION_PASSWORD:-}" ]; then
    echo "No SSH key and no STATION_PASSWORD in $CREDS" >&2
    exit 1
  fi
  expect <<EOF
set timeout 300
log_user 0
spawn sh -c "cat '$ARCHIVE' | ssh -o StrictHostKeyChecking=accept-new ${STATION_USER}@${STATION_HOST} 'cat > ${remote_path}'"
expect {
  -re "(?i)password:" { send "${STATION_PASSWORD}\r"; exp_continue }
  eof
}
EOF
}

echo "Deploy to ${STATION}:${REMOTE_DIR}"
ssh_with_auth "/system/bin/busybox-smp mkdir -p ${REMOTE_DIR}"
upload_archive "${REMOTE_DIR}/deploy.tgz"
ssh_with_auth "cd ${REMOTE_DIR} && (/system/bin/busybox-smp tar xzf deploy.tgz 2>/dev/null || tar xzf deploy.tgz) && rm -f deploy.tgz"
ssh_with_auth "sh ${REMOTE_DIR}/deploy-remote.sh"
echo "Done."
