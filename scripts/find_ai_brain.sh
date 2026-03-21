#!/usr/bin/env bash
set -euo pipefail

# Probe common localhost ports for an AI brain service implementing:
#   POST /init
#   POST /next
#
# Usage:
#   bash scripts/find_ai_brain.sh

HOST="${1:-127.0.0.1}"
PORTS=(8000 8001 8080 8081 5000 5001 5050 7000 9000)
TIMEOUT=2

post_json() {
  local url="$1"
  local data="$2"
  curl -sS -m "$TIMEOUT" -o /tmp/brain_probe_body.$$ -w "%{http_code}" \
    -H "Content-Type: application/json" -X POST "$url" -d "$data" 2>/dev/null || true
}

echo "Probing AI brain endpoints on ${HOST}..."
echo

found_any=0
for p in "${PORTS[@]}"; do
  init_url="http://${HOST}:${p}/init"
  next_url="http://${HOST}:${p}/next"

  init_code="$(post_json "$init_url" '{"session_id":"probe","width":1,"height":1,"cells":[{"walls":0}],"start_x":0,"start_y":0,"goal_x":0,"goal_y":0}')"
  next_code="$(post_json "$next_url" '{"session_id":"probe","x":0,"y":0}')"

  # Accept likely API route responses; ignore generic forbidden/auth pages.
  init_ok=0
  next_ok=0
  [[ "$init_code" == "200" || "$init_code" == "400" || "$init_code" == "404" || "$init_code" == "405" || "$init_code" == "422" ]] && init_ok=1 || true
  [[ "$next_code" == "200" || "$next_code" == "400" || "$next_code" == "404" || "$next_code" == "405" || "$next_code" == "422" ]] && next_ok=1 || true

  # Require both routes to be present-like and not "route missing" for both.
  if [[ $init_ok -eq 1 && $next_ok -eq 1 && ! ( "$init_code" == "404" && "$next_code" == "404" ) ]]; then
    found_any=1
    echo "Candidate found on port ${p}:"
    echo "  ${init_url}  (HTTP ${init_code})"
    echo "  ${next_url}  (HTTP ${next_code})"
    echo
    echo "Use this to launch autoplay:"
    echo "  MAZE_AUTOPLAY=1 MAZE_BRAIN_INIT_URL=\"${init_url}\" MAZE_BRAIN_NEXT_URL=\"${next_url}\" ./maze/maze_sdl2"
    echo
  fi
done

if [[ $found_any -eq 0 ]]; then
  echo "No AI brain endpoints detected on common ports."
  echo
  echo "Next steps:"
  echo "1) Ask teammate for their brain server start command."
  echo "2) Start it, then re-run: bash scripts/find_ai_brain.sh"
  echo "3) If they use a custom port, run:"
  echo "   MAZE_AUTOPLAY=1 MAZE_BRAIN_INIT_URL=\"http://HOST:PORT/init\" MAZE_BRAIN_NEXT_URL=\"http://HOST:PORT/next\" ./maze/maze_sdl2"
fi

