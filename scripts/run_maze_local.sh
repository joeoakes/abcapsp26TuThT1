#!/usr/bin/env bash
# =============================================================================
# run_maze_local.sh — Run the maze UI on your laptop with full robot pipeline
#
# What this does:
#   1. Starts the AI brain on the AI server
#   2. Starts ros_bridge + ros_bridge_node on the Mini Pupper
#   3. Starts a local proxy (port 9001) that relays brain calls AND forwards
#      each action to the ros_bridge so the robot physically moves
#   4. Launches the SDL2 maze app on your screen
#      Press P in the maze to enable AI autoplay → robot walks the maze
#
# Usage:
#   bash scripts/run_maze_local.sh
#
# Requirements:
#   brew install sshpass
#   pip3 install fastapi uvicorn httpx   (laptop only, one-time)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] .env not found. Copy .env.example and fill in credentials."
  exit 1
fi
set -a; source "$ENV_FILE"; set +a

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${BOLD}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERR ]${NC}  $*"; }

PROXY_PORT=9001
ROS_BRIDGE_PORT="${ROS_BRIDGE_PORT:-5050}"
BRAIN_PORT="${BRAIN_PORT:-8001}"

# Clean up everything on exit
cleanup() {
  echo ""
  info "Shutting down..."
  kill "$PROXY_PID" 2>/dev/null || true
  kill "$MAZE_PID"  2>/dev/null || true
  # Stop Pupper bridges + bringup
  sshpass -p "$PUPPER_PASS" ssh \
    -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    -o PreferredAuthentications=password -o PubkeyAuthentication=no \
    "${PUPPER_USER}@${PUPPER_HOST}" \
    "kill -9 \$(ps aux | grep -E 'uvicorn ros_bridge|ros_bridge_node|bringup.launch' | grep -v grep | awk '{print \$2}') 2>/dev/null; true" 2>/dev/null || true
  # Stop AI brain
  sshpass -p "$AI_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    "${AI_USER}@${AI_HOST}" \
    "tmux kill-session -t maze_brain2 2>/dev/null; true" 2>/dev/null || true
  ok "All stopped."
}
trap cleanup EXIT INT TERM

# =============================================================================
echo -e "\n${BOLD}══ Step 1: Start AI Brain ══${NC}"
# =============================================================================
info "Starting AI brain on ${AI_HOST}:${BRAIN_PORT}..."
sshpass -p "$AI_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  "${AI_USER}@${AI_HOST}" \
  "tmux kill-session -t maze_brain2 2>/dev/null; \
   tmux new-session -d -s maze_brain2 \
     'cd /home/team1tt/abcapsp26TuThT1/maze_brain2 && \
      REDIS_HOST=127.0.0.1 REDIS_PORT=6379 \
      OLLAMA_URL=${OLLAMA_URL} OLLAMA_MODEL=${OLLAMA_MODEL} \
      OLLAMA_EMBED_MODEL=${OLLAMA_EMBED_MODEL} \
      .venv/bin/python -m uvicorn maze_brain:app --host 0.0.0.0 --port ${BRAIN_PORT}'" 2>/dev/null
ok "Brain starting..."

# =============================================================================
echo -e "\n${BOLD}══ Step 2: Start ROS2 Bringup (stand up) ══${NC}"
# =============================================================================
info "Starting ROS2 bringup on Pupper (this makes it stand up)..."
# Write the bringup script first
sshpass -p "$PUPPER_PASS" ssh \
  -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  -o PreferredAuthentications=password -o PubkeyAuthentication=no \
  "${PUPPER_USER}@${PUPPER_HOST}" \
  "printf '#!/bin/bash\nsource /opt/ros/humble/setup.bash\nsource /home/ubuntu/ros2_ws/install/setup.bash\nexport ROS_DOMAIN_ID=42\nros2 launch mini_pupper_bringup bringup.launch.py > /tmp/bringup.log 2>&1\n' > /tmp/start_bringup.sh && chmod +x /tmp/start_bringup.sh" 2>/dev/null
# Kill any old bringup then launch fresh
sshpass -p "$PUPPER_PASS" ssh \
  -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  -o PreferredAuthentications=password -o PubkeyAuthentication=no \
  "${PUPPER_USER}@${PUPPER_HOST}" \
  "pkill -f bringup.launch 2>/dev/null; sleep 1; nohup /tmp/start_bringup.sh > /dev/null 2>&1 & echo ok" 2>/dev/null | grep -q "ok" \
  && ok "Bringup starting..." || warn "Bringup may have failed to start"

info "Waiting for bringup to initialise (15s)..."
sleep 15

# =============================================================================
echo -e "\n${BOLD}══ Step 3: Start Mini Pupper Bridges ══${NC}"
# =============================================================================
info "Starting ros_bridge HTTP on Pupper..."
sshpass -p "$PUPPER_PASS" ssh \
  -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  -o PreferredAuthentications=password -o PubkeyAuthentication=no \
  "${PUPPER_USER}@${PUPPER_HOST}" \
  "kill -9 \$(ps aux | grep -E 'uvicorn ros_bridge|ros_bridge_node' | grep -v grep | awk '{print \$2}') 2>/dev/null; sleep 1
   nohup bash -c 'cd ~/abcapsp26TuThT1/robot && \
     REDIS_HOST=127.0.0.1 REDIS_PORT=6379 \
     MAZE_STEP_DURATION=0.6 MAZE_TURN_DURATION=6.0 \
     python3 -m uvicorn ros_bridge:app --host 0.0.0.0 --port ${ROS_BRIDGE_PORT} \
     > /tmp/ros_bridge.log 2>&1' > /dev/null 2>&1 &
   sleep 2
   curl -s http://localhost:${ROS_BRIDGE_PORT}/health" 2>/dev/null | grep -q "ok" \
  && ok "ros_bridge HTTP running" || warn "ros_bridge may still be starting"

info "Starting ros_bridge_node on Pupper..."
sshpass -p "$PUPPER_PASS" ssh \
  -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  -o PreferredAuthentications=password -o PubkeyAuthentication=no \
  "${PUPPER_USER}@${PUPPER_HOST}" \
"cat > /tmp/start_ros_node.sh << 'NODEEOF'
#!/bin/bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/ros2_ws/install/setup.bash
cd /home/ubuntu/abcapsp26TuThT1/robot
export ROS_DOMAIN_ID=42
export REDIS_HOST=127.0.0.1
export REDIS_PORT=6379
export MAZE_STEP_LINEAR=0.15
export MAZE_STEP_ANGULAR=0.8
export MAZE_CELL_MOVE_DURATION=0.50
export MAZE_TURN_90_DURATION=6.0
python3 ros_bridge_node.py > /tmp/ros_bridge_node.log 2>&1
NODEEOF
chmod +x /tmp/start_ros_node.sh
nohup /tmp/start_ros_node.sh > /dev/null 2>&1 &
echo ok" 2>/dev/null | grep -q "ok" && ok "ros_bridge_node starting" || warn "ros_bridge_node may have failed"

# Wait for node to subscribe
info "Waiting for ros_bridge_node to subscribe to Redis..."
for i in $(seq 1 15); do
  COUNT=$(sshpass -p "$PUPPER_PASS" ssh \
    -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    -o PreferredAuthentications=password -o PubkeyAuthentication=no \
    "${PUPPER_USER}@${PUPPER_HOST}" \
    "redis-cli pubsub numsub maze_actions 2>/dev/null | tail -1" 2>/dev/null || echo 0)
  if [[ "$COUNT" == "1" ]]; then
    ok "ros_bridge_node subscribed"
    break
  fi
  sleep 1
done

# =============================================================================
echo -e "\n${BOLD}══ Step 4: Start Local Brain Proxy (port ${PROXY_PORT}) ══${NC}"
# =============================================================================
# Write proxy script inline
cat > /tmp/maze_brain_proxy.py << PYEOF
"""
Local proxy: sits between maze_sdl2 and the real AI brain.
- Forwards /init and /next to the real brain
- For /next, also POSTs the action to the ros_bridge so the robot moves
- The /next response is held until the ros_bridge returns (robot finishes move)
  so the maze app stays in sync with the physical robot
"""
import os, asyncio
from fastapi import FastAPI
from pydantic import BaseModel
import httpx

BRAIN_URL    = "http://${BRAIN_HOST}:${BRAIN_PORT}"
ROS_BRIDGE   = "http://${PUPPER_HOST}:${ROS_BRIDGE_PORT}"

app = FastAPI()

class InitReq(BaseModel):
    class Config: extra = "allow"

class NextReq(BaseModel):
    session_id: str = ""
    x: int = 0
    y: int = 0
    class Config: extra = "allow"

@app.post("/init")
async def init(payload: dict):
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BRAIN_URL}/init", json=payload, timeout=30)
    return r.json()

@app.post("/next")
async def next(payload: dict):
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BRAIN_URL}/next", json=payload, timeout=30)
    data = r.json()
    action = data.get("action", "")
    if action and action not in ("DONE", ""):
        # Forward to robot — this blocks until the robot finishes the move
        try:
            async with httpx.AsyncClient() as c:
                await c.post(f"{ROS_BRIDGE}/move", json={
                    "action": action,
                    "session_id": payload.get("session_id", ""),
                    "x": payload.get("x", 0),
                    "y": payload.get("y", 0),
                }, timeout=30)
        except Exception as e:
            print(f"[proxy] ros_bridge error: {e}")
    return data

@app.get("/health")
def health():
    return {"ok": True}
PYEOF

python3 -m uvicorn maze_brain_proxy:app \
  --app-dir /tmp \
  --host 127.0.0.1 \
  --port ${PROXY_PORT} \
  --log-level warning &
PROXY_PID=$!
sleep 1

# Verify proxy is up
curl -s "http://127.0.0.1:${PROXY_PORT}/health" | grep -q "ok" \
  && ok "Brain proxy running on port ${PROXY_PORT}" \
  || { error "Proxy failed to start"; exit 1; }

# Wait for AI brain to be ready
info "Waiting for AI brain to be ready..."
for i in $(seq 1 20); do
  if curl -s --max-time 2 "http://${BRAIN_HOST}:${BRAIN_PORT}/init" \
      -X POST -H "Content-Type: application/json" \
      -d '{}' 2>/dev/null | grep -qv "Connection refused"; then
    ok "AI brain responding"
    break
  fi
  [[ $i -eq 20 ]] && warn "Brain may still be loading — starting maze anyway"
  sleep 2
done

# =============================================================================
echo -e "\n${BOLD}══ Step 5: Launch Maze ══${NC}"
# =============================================================================
info "Launching maze app..."
echo ""
echo -e "  ${BOLD}Controls:${NC}"
echo -e "    Arrow keys / WASD — manual play"
echo -e "    ${GREEN}P${NC} — toggle AI autoplay (robot will physically walk the maze)"
echo -e "    L — open dashboard"
echo -e "    Q / Escape — quit"
echo ""

cd "$ROOT/maze"
MAZE_LOGGING_URL="${MAZE_LOGGING_URL}" \
MAZE_AI_URL="${MAZE_AI_URL}" \
MAZE_TLS_INSECURE="${MAZE_TLS_INSECURE:-1}" \
MAZE_BRAIN_INIT_URL="http://127.0.0.1:${PROXY_PORT}/init" \
MAZE_BRAIN_NEXT_URL="http://127.0.0.1:${PROXY_PORT}/next" \
./maze_sdl2 &
MAZE_PID=$!

wait "$MAZE_PID"
