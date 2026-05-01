#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Redis/bridge settings
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
ROS_BRIDGE_HOST="${ROS_BRIDGE_HOST:-127.0.0.1}"
ROS_BRIDGE_PORT="${ROS_BRIDGE_PORT:-5050}"
MAZE_MOVE_ACK_TIMEOUT="${MAZE_MOVE_ACK_TIMEOUT:-35.0}"

# Motion settings (grid-like behavior)
MAZE_ACTION_MODE="${MAZE_ACTION_MODE:-grid_absolute}"
MAZE_STEP_LINEAR="${MAZE_STEP_LINEAR:-0.13}"
MAZE_STEP_ANGULAR="${MAZE_STEP_ANGULAR:-0.8}"
MAZE_TURN_90_DURATION="${MAZE_TURN_90_DURATION:-2.05}"
MAZE_CELL_MOVE_DURATION="${MAZE_CELL_MOVE_DURATION:-1.40}"
MAZE_REVERSE_CELL_MOVE_DURATION="${MAZE_REVERSE_CELL_MOVE_DURATION:-1.40}"
MAZE_CMD_HZ="${MAZE_CMD_HZ:-15.0}"
MAZE_FORWARD_SIGN="${MAZE_FORWARD_SIGN:-1.0}"
MAZE_REVERSE_ON_OPPOSITE="${MAZE_REVERSE_ON_OPPOSITE:-1}"
MAZE_INITIAL_HEADING="${MAZE_INITIAL_HEADING:-0}"
MAZE_SWAP_UP_DOWN="${MAZE_SWAP_UP_DOWN:-1}"
MAZE_CMD_VEL_TOPIC="${MAZE_CMD_VEL_TOPIC:-/cmd_vel}"

echo "Starting Mini Pupper listener stack..."
echo "  Bridge: ${ROS_BRIDGE_HOST}:${ROS_BRIDGE_PORT}"
echo "  Redis: ${REDIS_HOST}:${REDIS_PORT}"
echo "  Mode: ${MAZE_ACTION_MODE}"
echo "  Topic: ${MAZE_CMD_VEL_TOPIC}"
echo "  Command rate: ${MAZE_CMD_HZ} Hz"
echo "  Move ack timeout: ${MAZE_MOVE_ACK_TIMEOUT}s"
echo "  Turn 90 duration: ${MAZE_TURN_90_DURATION}s"
echo "  Cell duration: ${MAZE_CELL_MOVE_DURATION}s"
echo "  Reverse on opposite: ${MAZE_REVERSE_ON_OPPOSITE}"
echo "  Swap up/down: ${MAZE_SWAP_UP_DOWN}"

cd "$ROOT_DIR"

# Stop older listeners if present.
pkill -f "uvicorn robot.ros_bridge:app --host ${ROS_BRIDGE_HOST} --port ${ROS_BRIDGE_PORT}" 2>/dev/null || true
pkill -f "python3 robot/ros_bridge_node.py" 2>/dev/null || true

# Start bridge in background.
nohup env \
  REDIS_HOST="$REDIS_HOST" \
  REDIS_PORT="$REDIS_PORT" \
  MAZE_MOVE_ACK_TIMEOUT="$MAZE_MOVE_ACK_TIMEOUT" \
  python3 -m uvicorn robot.ros_bridge:app --host "$ROS_BRIDGE_HOST" --port "$ROS_BRIDGE_PORT" \
  > /tmp/ros_bridge.log 2>&1 &

sleep 1
echo "Bridge started. Log: /tmp/ros_bridge.log"

# Start ROS node in foreground so operator sees status.
exec env \
  REDIS_HOST="$REDIS_HOST" \
  REDIS_PORT="$REDIS_PORT" \
  MAZE_ACTION_MODE="$MAZE_ACTION_MODE" \
  MAZE_STEP_LINEAR="$MAZE_STEP_LINEAR" \
  MAZE_STEP_ANGULAR="$MAZE_STEP_ANGULAR" \
  MAZE_TURN_90_DURATION="$MAZE_TURN_90_DURATION" \
  MAZE_CELL_MOVE_DURATION="$MAZE_CELL_MOVE_DURATION" \
  MAZE_REVERSE_CELL_MOVE_DURATION="$MAZE_REVERSE_CELL_MOVE_DURATION" \
  MAZE_CMD_HZ="$MAZE_CMD_HZ" \
  MAZE_FORWARD_SIGN="$MAZE_FORWARD_SIGN" \
  MAZE_REVERSE_ON_OPPOSITE="$MAZE_REVERSE_ON_OPPOSITE" \
  MAZE_INITIAL_HEADING="$MAZE_INITIAL_HEADING" \
  MAZE_SWAP_UP_DOWN="$MAZE_SWAP_UP_DOWN" \
  MAZE_CMD_VEL_TOPIC="$MAZE_CMD_VEL_TOPIC" \
  python3 robot/ros_bridge_node.py
