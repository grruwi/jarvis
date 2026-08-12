#!/usr/bin/env bash
# jarvis-say.sh — czyta tekst (stdin lub $*) głosem Pipera na wyjście PipeWire.
# Użycie:  echo "cześć" | jarvis-say.sh   |   jarvis-say.sh "cześć bambik"
set -euo pipefail
JV="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOICE="${JARVIS_VOICE:-$JV/voices/pl_PL-darkman-medium.onnx}"
PIPER="$JV/piper/piper"

# tekst: argumenty albo stdin
if [ "$#" -gt 0 ]; then TEXT="$*"; else TEXT="$(cat)"; fi
[ -z "${TEXT// }" ] && exit 0

# piper -> surowy PCM (s16le 22050 mono) -> paplay (PipeWire).
# LD_LIBRARY_PATH bo binarka wozi własne .so obok siebie.
LD_LIBRARY_PATH="$JV/piper" "$PIPER" --model "$VOICE" --output-raw <<<"$TEXT" 2>/dev/null \
  | paplay --raw --format=s16le --rate=22050 --channels=1
