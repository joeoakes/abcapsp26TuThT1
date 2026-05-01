#!/usr/bin/env bash
set -euo pipefail

# Run this on the Mini Pupper. It starts ROS bringup, the HTTP bridge, and
# the Redis-to-ROS /cmd_vel listener using the calibrated maze settings.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
ROS_BRIDGE_HOST="${ROS_BRIDGE_HOST:-0.0.0.0}"
ROS_BRIDGE_PORT="${ROS_BRIDGE_PORT:-5050}"
MAZE_MOVE_ACK_TIMEOUT="${MAZE_MOVE_ACK_TIMEOUT:-45.0}"

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

echo "Starting Mini Pupper maze stack from $ROOT_DIR"
echo "  ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "  Bridge=http://${ROS_BRIDGE_HOST}:${ROS_BRIDGE_PORT}"
echo "  Redis=${REDIS_HOST}:${REDIS_PORT}"
echo "  Mode=$MAZE_ACTION_MODE"
echo "  Linear=$MAZE_STEP_LINEAR Angular=$MAZE_STEP_ANGULAR"
echo "  Turn90=${MAZE_TURN_90_DURATION}s Cell=${MAZE_CELL_MOVE_DURATION}s"
echo "  Forward sign=$MAZE_FORWARD_SIGN Swap up/down=$MAZE_SWAP_UP_DOWN"

python3 -m py_compile robot/ros_bridge.py robot/ros_bridge_node.py

if command -v redis-cli >/dev/null 2>&1 && ! redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping >/dev/null 2>&1; then
  if command -v redis-server >/dev/null 2>&1; then
    echo "Starting local Redis..."
    redis-server --daemonize yes
    sleep 1
  else
    echo "Redis is not responding and redis-server is not on PATH." >&2
    exit 1
  fi
fi

cat > /tmp/start_minipupper_bringup.sh <<'BRINGUP'
#!/usr/bin/env bash
set -euo pipefail
source /opt/ros/humble/setup.bash
if [[ -f /home/ubuntu/ros2_ws/install/setup.bash ]]; then
  source /home/ubuntu/ros2_ws/install/setup.bash
fi
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
ros2 launch mini_pupper_bringup bringup.launch.py
BRINGUP
chmod +x /tmp/start_minipupper_bringup.sh

pkill -f "bringup.launch.py" 2>/dev/null || true
pkill -f "uvicorn robot.ros_bridge:app" 2>/dev/null || true
pkill -f "python3 robot/ros_bridge_node.py" 2>/dev/null || true
sleep 1

nohup env ROS_DOMAIN_ID="$ROS_DOMAIN_ID" /tmp/start_minipupper_bringup.sh \
  > /tmp/bringup.log 2>&1 &
echo "bringup_pid=$!"

nohup env \
  REDIS_HOST="$REDIS_HOST" \
  REDIS_PORT="$REDIS_PORT" \
  MAZE_MOVE_ACK_TIMEOUT="$MAZE_MOVE_ACK_TIMEOUT" \
  python3 -m uvicorn robot.ros_bridge:app --host "$ROS_BRIDGE_HOST" --port "$ROS_BRIDGE_PORT" \
  > /tmp/ros_bridge.log 2>&1 &
echo "bridge_pid=$!"

cat > /tmp/start_minipupper_ros_node.sh <<'NODE'
#!/usr/bin/env bash
set -euo pipefail
source /opt/ros/humble/setup.bash
if [[ -f /home/ubuntu/ros2_ws/install/setup.bash ]]; then
  source /home/ubuntu/ros2_ws/install/setup.bash
fi
cd /home/ubuntu/abcapsp26TuThT1
python3 robot/ros_bridge_node.py
NODE
chmod +x /tmp/start_minipupper_ros_node.sh

nohup env \
  ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
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
  /tmp/start_minipupper_ros_node.sh \
  > /tmp/ros_bridge_node.log 2>&1 &
echo "node_pid=$!"

sleep 8
curl -s "http://127.0.0.1:${ROS_BRIDGE_PORT}/health" || true
echo
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" pubsub numsub maze_actions || true
ps -ef | grep -E 'bringup.launch|uvicorn.*ros_bridge|ros_bridge_node.py' | grep -v grep || true
echo "--- ros_bridge_node tail ---"
tail -12 /tmp/ros_bridge_node.log || true
echo "--- bringup tail ---"
tail -8 /tmp/bringup.log || true
