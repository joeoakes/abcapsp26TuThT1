#!/usr/bin/env bash
# =============================================================================
# kill_maze.sh — Kill everything started by run_maze_local.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] .env not found."
  exit 1
fi
set -a; source "$ENV_FILE"; set +a

BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
info() { echo -e "${BOLD}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[ OK ]${NC}  $*"; }

# Kill local proxy
info "Killing local brain proxy..."
pkill -f "maze_brain_proxy" 2>/dev/null && ok "Proxy killed" || echo "  (proxy not running)"

# Kill local maze app
info "Killing maze app..."
pkill -f "maze_sdl2" 2>/dev/null && ok "Maze killed" || echo "  (maze not running)"

# Stop Pupper bridges + bringup
info "Killing Pupper ros_bridge, ros_bridge_node, and bringup..."
sshpass -p "$PUPPER_PASS" ssh \
  -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
  -o PreferredAuthentications=password -o PubkeyAuthentication=no \
  "${PUPPER_USER}@${PUPPER_HOST}" \
  "kill -9 \$(ps aux | grep -E 'uvicorn ros_bridge|ros_bridge_node|bringup.launch' | grep -v grep | awk '{print \$2}') 2>/dev/null; echo ok" \
  2>/dev/null | grep -q "ok" && ok "Pupper processes killed" || echo "  (nothing to kill on Pupper)"

# Stop AI brain
info "Killing AI brain (tmux session maze_brain2)..."
sshpass -p "$AI_PASS" ssh \
  -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
  "${AI_USER}@${AI_HOST}" \
  "tmux kill-session -t maze_brain2 2>/dev/null && echo ok || echo none" \
  2>/dev/null | grep -q "ok" && ok "AI brain killed" || echo "  (brain session not found)"

echo ""
ok "All done."
