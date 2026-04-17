#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Where the robot bridge listens. If maze_brain runs on the same host as Mini Pupper,
# keep localhost. If maze_brain runs on your laptop, point to robot IP.
ROBOT_BRIDGE_URL="${ROBOT_BRIDGE_URL:-http://10.170.8.209:5050}"
ROBOT_BRIDGE_TIMEOUT_S="${ROBOT_BRIDGE_TIMEOUT_S:-2.0}"
ROBOT_BRIDGE_REQUIRED="${ROBOT_BRIDGE_REQUIRED:-1}"
MAZE_BRAIN_HOST="${MAZE_BRAIN_HOST:-0.0.0.0}"
MAZE_BRAIN_PORT="${MAZE_BRAIN_PORT:-8010}"

echo "Starting maze_brain with robot forwarding..."
echo "  ROBOT_BRIDGE_URL=${ROBOT_BRIDGE_URL}"
echo "  MAZE_BRAIN=${MAZE_BRAIN_HOST}:${MAZE_BRAIN_PORT}"

cd "$ROOT_DIR/maze_brain"

exec env \
  ROBOT_BRIDGE_URL="$ROBOT_BRIDGE_URL" \
  ROBOT_BRIDGE_TIMEOUT_S="$ROBOT_BRIDGE_TIMEOUT_S" \
  ROBOT_BRIDGE_REQUIRED="$ROBOT_BRIDGE_REQUIRED" \
  python3 -m uvicorn maze_brain:app --host "$MAZE_BRAIN_HOST" --port "$MAZE_BRAIN_PORT"

