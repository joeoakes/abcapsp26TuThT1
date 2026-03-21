#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CADDY_BIN="${CADDY_BIN:-}"
if [[ -z "${CADDY_BIN}" ]]; then
  if [[ -x "$ROOT_DIR/.tools/caddy" ]]; then
    CADDY_BIN="$ROOT_DIR/.tools/caddy"
  elif command -v caddy >/dev/null 2>&1; then
    CADDY_BIN="$(command -v caddy)"
  fi
fi

if [[ -z "${CADDY_BIN}" ]]; then
  echo "Caddy is not installed."
  echo "Install locally (no sudo) with: scripts/install_caddy_local.sh"
  exit 1
fi

echo "Starting FastAPI backend on http://127.0.0.1:8080 ..."
(
  cd "$ROOT_DIR"
  python -m uvicorn dashboard.main:app --host 127.0.0.1 --port 8080
) &
UVICORN_PID=$!

cleanup() {
  echo
  echo "Stopping..."
  kill "$UVICORN_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Starting Caddy reverse proxy on https://localhost:8443 ..."
echo "Dashboard URL: https://localhost:8443/index.html"
echo
echo "If your browser warns about cert trust, run once:"
echo "  \"$CADDY_BIN\" trust"
echo

cd "$ROOT_DIR/dashboard"
# Keep all Caddy state inside the repo (works without admin perms).
export XDG_DATA_HOME="$ROOT_DIR/.caddy-data"
export XDG_CONFIG_HOME="$ROOT_DIR/.caddy-config"
mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME"

"$CADDY_BIN" run --config "$ROOT_DIR/dashboard/Caddyfile"

