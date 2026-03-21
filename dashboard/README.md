# Mini-Pupper Mission Dashboard

Real-time dashboard UI + FastAPI backend for live telemetry, mission history, robot health, and upstream connectivity status.

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

## Run Locally

### 1) Start dashboard backend

From repo root:

```bash
python -m uvicorn dashboard.main:app --host 127.0.0.1 --port 8443
```

### 2) Serve `index.html`

From repo root:

```bash
python -m http.server 8000
```

Open:
- `http://127.0.0.1:8000/dashboard/index.html?apiPort=8443`

---

## Test Live Ingest

```bash
curl -X POST http://127.0.0.1:8443/move \
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


