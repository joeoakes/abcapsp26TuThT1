#!/usr/bin/env bash
set -euo pipefail

curl -sS --max-time 5 \
  -X POST http://127.0.0.1:5050/move \
  -H 'Content-Type: application/json' \
  -d '{"action":"DONE","session_id":"stop-script","x":0,"y":0}' >/dev/null 2>&1 || true

pkill -f "uvicorn robot.ros_bridge:app" 2>/dev/null || true
pkill -f "python3 robot/ros_bridge_node.py" 2>/dev/null || true
pkill -f "bringup.launch.py" 2>/dev/null || true

echo "Mini Pupper maze stack stopped."
