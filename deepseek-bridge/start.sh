#!/system/bin/sh
BB=/system/bin/busybox-smp
DIR=/data/quasar/deepseek-bridge
if [ -f "$DIR/bridge.pid" ]; then
    pid=$("$BB" cat "$DIR/bridge.pid" 2>/dev/null)
    case "$pid" in
        ''|*[!0-9]*) ;;
        *) if "$BB" kill -0 "$pid" 2>/dev/null; then
            exit 0
        fi ;;
    esac
fi
i=0
while [ ! -x /opt/bin/python3 ] || [ ! -x /opt/lib/ld-linux-aarch64.so.1 ]; do
  i=$((i + 1))
  if [ "$i" -gt 30 ]; then
    echo "python is not ready" >>"$DIR/bridge.log"
    exit 1
  fi
  "$BB" sleep 1
done
export SSL_CERT_FILE=/opt/etc/ssl/certs/ca-certificates.crt
export LD_LIBRARY_PATH=/opt/lib
export PYTHONUNBUFFERED=1
export BRIDGE_MODE="${BRIDGE_MODE:-hybrid}"
if [ -f "$DIR/bridge.env" ]; then
  set -a
  . "$DIR/bridge.env"
  set +a
fi
cd "$DIR" || exit 1
"$BB" setsid /opt/bin/python3 "$DIR/bridge.py" >>"$DIR/bridge.log" 2>&1 &
echo $! > "$DIR/bridge.pid"
