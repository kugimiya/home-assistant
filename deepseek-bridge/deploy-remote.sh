#!/system/bin/sh
# Run on the station after rsync (from deploy-to-station.sh).
BB=/system/bin/busybox-smp
DIR=/data/quasar/deepseek-bridge
ENV="$DIR/bridge.env"

"$BB" mkdir -p "$DIR/data"
touch "$ENV"

set_kv() {
  if "$BB" grep -q "^$1=" "$ENV" 2>/dev/null; then
    "$BB" sed -i "s/^$1=.*/$1=$2/" "$ENV"
  else
    echo "$1=$2" >>"$ENV"
  fi
}

set_kv BRIDGE_PIPELINE 1
set_kv JOBS_DB_PATH /data/quasar/deepseek-bridge/data/jobs.db
set_kv BRIDGE_JOB_MODEL deepseek-chat
set_kv BRIDGE_JOB_MAX_TOOL_ROUNDS 24
set_kv BRIDGE_JOB_STEP_TIMEOUT_SEC 120
set_kv BRIDGE_JOB_MAX_API_CALLS 16
set_kv BRIDGE_JOB_MAX_API_CALLS_TOTAL 48
set_kv BRIDGE_JOB_MAX_INTROSPECTIONS 3
set_kv BRIDGE_MAX_CONCURRENT_JOBS 1
set_kv BRIDGE_PIPELINE_STUB_WORKER 0
"$BB" grep -q '^BRIDGE_MODE=' "$ENV" || echo 'BRIDGE_MODE=hybrid' >>"$ENV"

if [ -f "$DIR/bridge.pid" ]; then
  pid=$("$BB" cat "$DIR/bridge.pid" 2>/dev/null)
  case "$pid" in
    ''|*[!0-9]*) ;;
    *)
      if "$BB" kill -0 "$pid" 2>/dev/null; then
        "$BB" kill "$pid" 2>/dev/null
        "$BB" sleep 1
      fi
      ;;
  esac
fi

sh "$DIR/start.sh"
"$BB" sleep 2

if [ -f "$DIR/bridge.pid" ] && "$BB" kill -0 "$("$BB" cat "$DIR/bridge.pid")" 2>/dev/null; then
  echo bridge_running
else
  echo bridge_not_started
fi

/opt/bin/python3 "$DIR/bridge.py" selftest 2>/dev/null | "$BB" tail -1 || true
"$BB" tail -8 "$DIR/bridge.log" 2>/dev/null || true
