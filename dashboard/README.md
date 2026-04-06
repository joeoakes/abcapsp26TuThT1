# Mini-Pupper Mission Dashboard

Real-time dashboard UI + FastAPI backend for live telemetry, mission history, robot health, and upstream connectivity status.

![Mini-Pupper Mission Dashboard — Team 1, Spring 2026](/docs/Dashboard.png)

*Live dashboard: robot health, move breakdown, telemetry table, mission history, stats bar, and upstream status.*

---

## Current Architecture

```
Maze App (SDL2)
   -> POST /move (HTTPS, usually :8443) to Logging + AI services
Dashboard Backend (FastAPI)
   -> WebSocket /telemetry for live updates
   -> GET /recent from maze_moves.log
   -> GET /recent_missions from maze_moves.log
   -> GET /upstream_status for Logging + AI reachability
Dashboard Frontend (index.html)
   -> live table, mission cards, stats bar, robot health, AI-style insight text
```

Default upstream hosts currently shown/used in this project:
- Logging server: `10.170.8.130:8443`
- AI server: `10.170.8.109:8443`

---

## Collections / Key Names

- MongoDB collection (team logging target): `team1ttmoves`
- Redis should be treated as key namespace/prefix: `team1tt`
  - exact Redis key pattern can vary by server implementation

---

## Features Implemented

- Live telemetry ingest via `POST /move` (alias of `/ingest`)
- WebSocket broadcast on `/telemetry`
- Recent telemetry pagination from `maze/maze_moves.log` (`/recent`, default limit 100)
- Mission history extraction from `maze/maze_moves.log` (`/recent_missions`, newest first)
- Mission status classification: `success`, `aborted`, `in_progress`
- Dynamic stats bar (moves, distance, duration, missions run, success rate, robots online)
- Dynamic robot health:
  - last seen (relative time)
  - active/idle/offline status
  - battery percent
  - battery state (`Charging`, `Discharging`, `Full`, `Low`, `Unknown`)
- Upstream status indicators:
  - footer per-service indicator (Logging / AI)
  - combined header pill (online/partial/offline)
- Upstream status backend caching (5s) to avoid expensive repeated TLS checks

---

## Run locally (HTTPS — recommended)

From repo root:

```bash
bash scripts/run_dashboard_https_local.sh
```

- **Public URL:** `https://127.0.0.1:8443/index.html` (or `https://localhost:8443/index.html`)
- Caddy terminates TLS; FastAPI runs on **`127.0.0.1:8080`** internally.
- If the browser warns about the certificate, run `caddy trust` once (or use `-k` with `curl`).

Extra origins for CORS (optional):

```bash
export DASHBOARD_CORS_ORIGINS="https://your-laptop.example:8443"
```

### Optional: HTTP-only quick dev (not full HTTPS parity)

```bash
python -m uvicorn dashboard.main:app --host 127.0.0.1 --port 8443
python -m http.server 8000   # serve dashboard/ from repo root; open /dashboard/index.html?apiPort=8443
```

---

## Test live ingest (HTTPS)

```bash
curl -sk -X POST https://127.0.0.1:8443/move \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "player_move",
    "input": { "device": "joystick", "move_sequence": 1 },
    "player": { "position": { "x": 1, "y": 2 } },
    "goal_reached": false,
    "timestamp": "2026-01-25T11:42:18Z"
  }'
```

Battery + charging example fields supported:

```json
{
  "battery_pct": 71,
  "is_charging": true
}
```

Also supported under `robot`:
- `robot.battery_pct`
- `robot.charging` / `robot.is_charging`
- `robot.battery_status` / `robot.battery_state`

---

## HTTPS / Reverse Proxy

This repo includes local HTTPS reverse-proxy helpers (Caddy-based) under `scripts/` and `dashboard/Caddyfile`.
Use these when you need dashboard access via `https://127.0.0.1:8443`.

---

## Running on Raspberry Pi Game Hat

Start everything with these commands (SSH in as `pi@10.170.8.190`):

```bash
# Start dashboard backend + file server
cd ~/abcapsp26TuThT1
nohup python3 -m http.server 8000 > /dev/null 2>&1 &
nohup uvicorn dashboard.main:app --host 0.0.0.0 --port 8080 > /dev/null 2>&1 &

# Start X display
nohup Xorg :0 vt1 > /tmp/xorg.log 2>&1 &
sleep 5 && DISPLAY=:0 xhost +

# Start maze app
cd ~/abcapsp26TuThT1/maze
DISPLAY=:0 MAZE_LOGGING_URL=https://10.170.8.130:8443/move \
  MAZE_AI_URL=https://10.170.8.109:8443/move \
  MAZE_TLS_INSECURE=1 \
  nohup ./maze_sdl2_pi > /tmp/maze.log 2>&1 &
```

Open dashboard in browser:
```
http://10.170.8.190:8000/dashboard/index.html?apiPort=8080
```

---

## Simulator (No Hardware Required)

Simulates the Mini Pupper solving the maze and streams live telemetry to the dashboard:

```bash
# Start the dashboard first, then:
python3 scripts/simulate_pupper.py --delay 0.3
```

Options:
- `--delay 0.4` — seconds between moves (default 0.4)
- `--seed 42` — fixed maze seed for repeatable runs
- `--url http://127.0.0.1:8080/ingest` — custom ingest URL

---

## Systemd Services (Raspberry Pi)

The dashboard runs as systemd services on the Pi so it survives reboots:

```bash
# Check status
sudo systemctl status dashboard
sudo systemctl status dashboard-files

# Restart
sudo systemctl restart dashboard
sudo systemctl restart dashboard-files
```


