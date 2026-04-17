#!/usr/bin/env bash
# =============================================================================
# startup.sh — Boot the full Team 1TT system
#
# Usage:
#   bash scripts/startup.sh            # start everything
#   bash scripts/startup.sh --no-maze  # skip maze app (dashboard + brain only)
#   bash scripts/startup.sh --sim      # run simulator instead of real maze
#
# Requirements:
#   brew install sshpass   (macOS)
#   apt install sshpass    (Linux)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$ROOT/.env"

# ── Load .env ─────────────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] .env file not found at $ENV_FILE"
  echo "        Copy .env.example to .env and fill in your credentials."
  exit 1
fi
set -a; source "$ENV_FILE"; set +a

# ── Flags ─────────────────────────────────────────────────────────────────────
NO_MAZE=false
RUN_SIM=false
for arg in "$@"; do
  [[ "$arg" == "--no-maze" ]] && NO_MAZE=true
  [[ "$arg" == "--sim"     ]] && RUN_SIM=true
done

# ── Helpers ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
BOLD='\033[1m'

info()    { echo -e "${BOLD}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR ]${NC}  $*"; }
section() { echo -e "\n${BOLD}══ $* ══${NC}"; }

ssh_run() {
  local user="$1" pass="$2" host="$3" cmd="$4"
  sshpass -p "$pass" ssh -o StrictHostKeyChecking=no \
    -o ConnectTimeout=10 \
    -o ServerAliveInterval=5 \
    "${user}@${host}" "$cmd" 2>&1
}

ssh_bg() {
  # Run command in background on remote host (uses nohup internally)
  local user="$1" pass="$2" host="$3" cmd="$4"
  sshpass -p "$pass" ssh -o StrictHostKeyChecking=no \
    -o ConnectTimeout=10 \
    "${user}@${host}" "nohup bash -c '$cmd' > /tmp/startup_bg.log 2>&1 &" 2>&1 || true
}

check_reachable() {
  local name="$1" host="$2" port="${3:-22}"
  if nc -z -w3 "$host" "$port" 2>/dev/null; then
    ok "$name ($host) reachable"
    return 0
  else
    error "$name ($host:$port) not reachable — are you on VPN?"
    return 1
  fi
}

# =============================================================================
section "Checking connectivity"
# =============================================================================
ALL_OK=true
check_reachable "Game Hat"       "$PI_HOST"      || ALL_OK=false
check_reachable "Mini Pupper"    "$PUPPER_HOST"  || ALL_OK=false
check_reachable "Logging Server" "$LOGGING_HOST" || ALL_OK=false
check_reachable "AI Server"      "$AI_HOST"      || ALL_OK=false

if [[ "$ALL_OK" == false ]]; then
  warn "Some hosts unreachable. Continuing anyway — some steps may fail."
fi

# =============================================================================
section "Logging Server (10.170.8.130)"
# =============================================================================
info "Checking team1tt-mongo service..."
STATUS=$(ssh_run "$LOGGING_USER" "$LOGGING_PASS" "$LOGGING_HOST" \
  "systemctl --user is-active team1tt-mongo 2>/dev/null || echo inactive")

if [[ "$STATUS" == "active" ]]; then
  ok "team1tt-mongo already running"
else
  info "Starting team1tt-mongo..."
  ssh_run "$LOGGING_USER" "$LOGGING_PASS" "$LOGGING_HOST" \
    "systemctl --user start team1tt-mongo"
  sleep 2
  ok "team1tt-mongo started"
fi

# Verify
RESP=$(ssh_run "$LOGGING_USER" "$LOGGING_PASS" "$LOGGING_HOST" \
  "curl -sk https://127.0.0.1:8443/move -X POST -H 'Content-Type: application/json' -d '{\"ping\":1}'")
[[ "$RESP" == *"ok"* ]] && ok "Logging server responding" || warn "Logging server not responding: $RESP"

# =============================================================================
section "AI Server (10.170.8.109)"
# =============================================================================
info "Checking team1tt-redis service..."
STATUS=$(ssh_run "$AI_USER" "$AI_PASS" "$AI_HOST" \
  "systemctl --user is-active team1tt-redis 2>/dev/null || echo inactive")

if [[ "$STATUS" == "active" ]]; then
  ok "team1tt-redis already running"
else
  info "Starting team1tt-redis..."
  ssh_run "$AI_USER" "$AI_PASS" "$AI_HOST" \
    "systemctl --user start team1tt-redis"
  sleep 2
  ok "team1tt-redis started"
fi

RESP=$(ssh_run "$AI_USER" "$AI_PASS" "$AI_HOST" \
  "curl -sk https://127.0.0.1:8443/move -X POST -H 'Content-Type: application/json' -d '{\"ping\":1}'")
[[ "$RESP" == *"ok"* ]] && ok "AI server responding" || warn "AI server not responding: $RESP"

# =============================================================================
section "AI Brain — AI Server (10.170.8.109)"
# =============================================================================
info "Checking if brain server is already running on port $BRAIN_PORT..."
BRAIN_UP=$(ssh_run "$AI_USER" "$AI_PASS" "$AI_HOST" \
  "curl -s http://localhost:${BRAIN_PORT}/health 2>/dev/null || echo dead")

if [[ "$BRAIN_UP" == *"true"* ]]; then
  ok "AI Brain already running on port $BRAIN_PORT"
else
  info "Running run_everything.sh on AI server..."
  ssh_run "$AI_USER" "$AI_PASS" "$AI_HOST" \
    "pkill -f 'uvicorn maze_brain' 2>/dev/null; sleep 1; true"

  # run_everything.sh uses tmux — run it detached so SSH doesn't block
  sshpass -p "$AI_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    "${AI_USER}@${AI_HOST}" \
    "cd /home/team1tt/abcapsp26TuThT1 && \
     REDIS_HOST=${REDIS_HOST} \
     REDIS_PORT=${REDIS_PORT} \
     OLLAMA_URL=${OLLAMA_URL} \
     OLLAMA_MODEL=${OLLAMA_MODEL} \
     OLLAMA_EMBED_MODEL=${OLLAMA_EMBED_MODEL} \
     tmux new-session -d -s maze_brain2 \
       'bash /home/team1tt/abcapsp26TuThT1/run_everything.sh' 2>/dev/null || true" 2>&1 || true

  sleep 6
  BRAIN_UP=$(ssh_run "$AI_USER" "$AI_PASS" "$AI_HOST" \
    "curl -s http://localhost:${BRAIN_PORT}/health 2>/dev/null || echo dead")
  [[ "$BRAIN_UP" == *"true"* ]] && ok "AI Brain started via run_everything.sh" \
    || warn "AI Brain may still be starting — check tmux on AI server: tmux attach -t maze_brain2"
fi

# =============================================================================
section "Game Hat — Dashboard (10.170.8.190)"
# =============================================================================
info "Starting dashboard backend and file server..."
ssh_run "$PI_USER" "$PI_PASS" "$PI_HOST" \
  "pkill -f uvicorn 2>/dev/null; pkill -f 'http.server 8000' 2>/dev/null; sleep 1; true"

ssh_bg "$PI_USER" "$PI_PASS" "$PI_HOST" \
  "cd ~/abcapsp26TuThT1 && \
   python3 /home/pi/.local/bin/uvicorn dashboard.main:app --host 0.0.0.0 --port 8080 > /tmp/dashboard.log 2>&1"

ssh_bg "$PI_USER" "$PI_PASS" "$PI_HOST" \
  "cd ~/abcapsp26TuThT1 && python3 -m http.server 8000 > /tmp/files.log 2>&1"

sleep 3
DASH=$(ssh_run "$PI_USER" "$PI_PASS" "$PI_HOST" \
  "curl -s http://localhost:8080/upstream_status 2>/dev/null || echo dead")
[[ "$DASH" == *"logging_server"* ]] && ok "Dashboard API running" || warn "Dashboard may not be ready yet"

# =============================================================================
section "Game Hat — Xorg + Maze App (10.170.8.190)"
# =============================================================================
if [[ "$NO_MAZE" == true ]]; then
  warn "--no-maze flag set, skipping maze app"
elif [[ "$RUN_SIM" == true ]]; then
  info "Running simulator instead of maze app..."
  python3 "$ROOT/scripts/simulate_pupper.py" \
    --url "http://${PI_HOST}:8080/ingest" \
    --delay 0.4 &
  ok "Simulator started (PID $!)"
else
  info "Starting Xorg..."
  ssh_run "$PI_USER" "$PI_PASS" "$PI_HOST" \
    "sudo rm -f /tmp/.X0-lock /tmp/.X11-unix/X0 2>/dev/null; pkill -x Xorg 2>/dev/null; sleep 1; true"

  ssh_bg "$PI_USER" "$PI_PASS" "$PI_HOST" \
    "Xorg :0 vt1 > /tmp/xorg.log 2>&1"

  sleep 5
  ssh_run "$PI_USER" "$PI_PASS" "$PI_HOST" "DISPLAY=:0 xhost +" 2>/dev/null || true

  info "Starting maze app..."
  ssh_run "$PI_USER" "$PI_PASS" "$PI_HOST" \
    "pkill -f maze_sdl2_pi 2>/dev/null; sleep 1; true"

  ssh_bg "$PI_USER" "$PI_PASS" "$PI_HOST" \
    "cd ~/abcapsp26TuThT1/maze && \
     DISPLAY=:0 \
     MAZE_LOGGING_URL=${MAZE_LOGGING_URL} \
     MAZE_AI_URL=${MAZE_AI_URL} \
     MAZE_TLS_INSECURE=${MAZE_TLS_INSECURE} \
     MAZE_BRAIN_INIT_URL=${MAZE_BRAIN_INIT_URL} \
     MAZE_BRAIN_NEXT_URL=${MAZE_BRAIN_NEXT_URL} \
     ./maze_sdl2_pi > /tmp/maze.log 2>&1"

  sleep 4

  # Focus window
  WIN=$(ssh_run "$PI_USER" "$PI_PASS" "$PI_HOST" \
    "DISPLAY=:0 xdotool search --name 'SDL2 Maze' 2>/dev/null | head -1" || echo "")
  if [[ -n "$WIN" ]]; then
    ssh_run "$PI_USER" "$PI_PASS" "$PI_HOST" \
      "DISPLAY=:0 xdotool windowfocus --sync $WIN && DISPLAY=:0 xdotool windowraise $WIN" 2>/dev/null || true
    ok "Maze app running and focused (window $WIN)"
  else
    warn "Maze window not found yet — may still be starting"
  fi
fi

# =============================================================================
section "Summary"
# =============================================================================
echo ""
echo -e "  ${GREEN}Logging server${NC}  https://${LOGGING_HOST}:8443/move"
echo -e "  ${GREEN}AI server${NC}       https://${AI_HOST}:8443/move"
echo -e "  ${GREEN}AI Brain${NC}        http://${PUPPER_HOST}:${BRAIN_PORT}/health"
echo -e "  ${GREEN}Dashboard${NC}       http://${PI_HOST}:8000/dashboard/index.html?apiPort=8080"
echo ""
echo -e "  ${BOLD}To enable AI autoplay on the Game Hat, press P in the maze window.${NC}"
echo ""
