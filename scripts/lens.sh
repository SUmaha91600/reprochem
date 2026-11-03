#!/usr/bin/env bash
# ReproChem Lens: spoken questions, answers as diagrams and narrated video.
#
#   bash scripts/lens.sh            # opens http://localhost:8765 (or the next free port)
#   PORT=8800 bash scripts/lens.sh  # a given port
#
# Chrome recommended (Safari works too, with dictation enabled in macOS).
# The demo uses the browser's speech recognition, which needs a network.
# Offline, the text box and the buttons at the bottom do the same job.
# Voice benchmark: the same address + /voicetest.html
set -euo pipefail
cd "$(dirname "$0")/../app/lens"
PORT="${PORT:-8765}"
# Another application may already listen on the port: take the next free one,
# otherwise the browser would open that other application.
busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
for _ in $(seq 1 20); do
  busy "$PORT" || break
  echo "port $PORT already in use by another application, trying $((PORT + 1))"
  PORT=$((PORT + 1))
done
python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
sleep 1
if ! kill -0 "$SRV" 2>/dev/null; then
  echo "the Lens server could not start on port $PORT" >&2; exit 1
fi
URL="http://localhost:$PORT"
PAGE="${1:-}"                       # bash scripts/lens.sh voicetest.html
if [[ -d "/Applications/Google Chrome.app" ]]; then open -a "Google Chrome" "$URL/$PAGE"
else open "$URL/$PAGE"; fi
echo "ReproChem Lens:   $URL"
echo "Voice benchmark:  $URL/voicetest.html"
echo "(Ctrl-C to stop)"
wait $SRV
