#!/usr/bin/env bash
set -euo pipefail

pkill -f "uvicorn robot.ros_bridge:app" 2>/dev/null || true
pkill -f "python3 robot/ros_bridge_node.py" 2>/dev/null || true

echo "Mini Pupper listener processes stopped."

