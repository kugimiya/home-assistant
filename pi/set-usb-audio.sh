#!/usr/bin/env bash
# Prepare USB sound card before jarvis-pi starts: default device + boot volume levels.
set -euo pipefail

PI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PI_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

ARECORD_DEVICE="${ARECORD_DEVICE:-plughw:Device,0}"
MIC_BOOT_PERCENT="${MIC_BOOT_PERCENT:-45}"
SPEAKER_BOOT_PERCENT="${SPEAKER_BOOT_PERCENT:-25}"
MIC_ALSA_CONTROL="${MIC_ALSA_CONTROL:-Mic}"
SPEAKER_ALSA_CONTROL="${SPEAKER_ALSA_CONTROL:-Speaker}"

mixer_device_from_pcm() {
  local device="${1:-}"
  device="${device// /}"
  if [[ -z "$device" ]]; then
    device="default"
  fi
  local lowered="${device,,}"
  local prefix
  for prefix in plughw: hw: sysdefault: plug:; do
    if [[ "$lowered" == "$prefix"* ]]; then
      local card="${device#"$prefix"}"
      card="${card%%,*}"
      card="${card// /}"
      if [[ -n "$card" ]]; then
        echo "hw:$card"
        return 0
      fi
    fi
  done
  echo "$device"
}

card_id_from_mixer() {
  local mixer="$1"
  if [[ "$mixer" == hw:* ]]; then
    echo "${mixer#hw:}"
  else
    echo "$mixer"
  fi
}

mixer="$(mixer_device_from_pcm "$ARECORD_DEVICE")"
card_id="$(card_id_from_mixer "$mixer")"

if ! command -v amixer >/dev/null 2>&1; then
  echo "amixer not found; install alsa-utils" >&2
  exit 1
fi

if ! amixer -D "$mixer" scontrols >/dev/null 2>&1; then
  echo "ALSA card not ready: $mixer" >&2
  exit 1
fi

ASOUNDRC="${HOME}/.asoundrc"
MARKER="# jarvis-pi managed"
if [[ -f "$ASOUNDRC" ]] && ! grep -q "$MARKER" "$ASOUNDRC"; then
  echo "Refusing to overwrite $ASOUNDRC (not jarvis-pi managed). Remove it or add the marker." >&2
  exit 1
fi

cat >"$ASOUNDRC" <<EOF
$MARKER
pcm.!default {
    type plug
    slave.pcm "plughw:${card_id},0"
}
ctl.!default {
    type hw
    card ${card_id}
}
EOF

if command -v wpctl >/dev/null 2>&1; then
  while IFS= read -r id; do
    [[ -z "$id" ]] && continue
    inspect="$(wpctl inspect "$id" 2>/dev/null || true)"
    [[ -z "$inspect" ]] && continue
    if ! grep -Fq "alsa.id = \"${card_id}\"" <<<"$inspect"; then
      continue
    fi
    media_class="$(sed -n 's/.*media.class = "\([^"]*\)".*/\1/p' <<<"$inspect" | head -1)"
    case "$media_class" in
      Audio/Sink | Audio/Source)
        wpctl set-default "$id" 2>/dev/null || true
        ;;
    esac
  done < <(wpctl status 2>/dev/null | sed -n 's/^[[:space:]]*\*[[:space:]]*\([0-9]\+\)\..*/\1/p; s/^[[:space:]]*\([0-9]\+\)\..*/\1/p' | sort -nu)
fi

amixer_optional() {
  amixer -D "$mixer" sset "$1" "$2" >/dev/null 2>&1 || true
}

amixer -D "$mixer" sset "$MIC_ALSA_CONTROL" "${MIC_BOOT_PERCENT}%"
amixer_optional "$MIC_ALSA_CONTROL" cap
amixer_optional "$MIC_ALSA_CONTROL" unmute

amixer -D "$mixer" sset "$SPEAKER_ALSA_CONTROL" "${SPEAKER_BOOT_PERCENT}%"
amixer_optional "$SPEAKER_ALSA_CONTROL" unmute

echo "USB audio ready: card=$card_id mic=${MIC_BOOT_PERCENT}% speaker=${SPEAKER_BOOT_PERCENT}%"
