#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Redis/bridge settings
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
ROS_BRIDGE_HOST="${ROS_BRIDGE_HOST:-127.0.0.1}"
ROS_BRIDGE_PORT="${ROS_BRIDGE_PORT:-5050}"

# Motion settings (grid-like behavior)
MAZE_ACTION_MODE="${MAZE_ACTION_MODE:-grid_absolute}"
MAZE_STEP_LINEAR="${MAZE_STEP_LINEAR:-0.15}"
MAZE_STEP_ANGULAR="${MAZE_STEP_ANGULAR:-0.8}"
MAZE_TURN_90_DURATION="${MAZE_TURN_90_DURATION:-0.85}"
MAZE_CELL_MOVE_DURATION="${MAZE_CELL_MOVE_DURATION:-0.60}"
MAZE_CMD_VEL_TOPIC="${MAZE_CMD_VEL_TOPIC:-/cmd_vel}"

echo "Starting Mini Pupper listener stack..."
echo "  Bridge: ${ROS_BRIDGE_HOST}:${ROS_BRIDGE_PORT}"
echo "  Redis: ${REDIS_HOST}:${REDIS_PORT}"
echo "  Mode: ${MAZE_ACTION_MODE}"
echo "  Topic: ${MAZE_CMD_VEL_TOPIC}"

cd "$ROOT_DIR"

# Stop older listeners if present.
pkill -f "uvicorn robot.ros_bridge:app --host ${ROS_BRIDGE_HOST} --port ${ROS_BRIDGE_PORT}" 2>/dev/null || true
pkill -f "python3 robot/ros_bridge_node.py" 2>/dev/null || true

# Start bridge in background.
nohup env \
  REDIS_HOST="$REDIS_HOST" \
  REDIS_PORT="$REDIS_PORT" \
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
  MAZE_CMD_VEL_TOPIC="$MAZE_CMD_VEL_TOPIC" \
  python3 robot/ros_bridge_node.py

