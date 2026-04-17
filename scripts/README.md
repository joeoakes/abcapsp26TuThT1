# Scripts
- **build.sh** — Build all maze applications (SDL2 client, HTTPS Mongo/Redis/Mini-Pupper servers). Run from repo root: `./scripts/build.sh`
- **gen_mtls_certs.sh** — Generate CA and client certificates for mTLS. Run from repo root: `./scripts/gen_mtls_certs.sh`. See `https/README.md` for mTLS usage.
- **find_ai_brain.sh** — Probe localhost for AI brain `/init` and `/next` endpoints, then print a ready-to-run autoplay command.
- **run_maze_local.sh** — Boot the full robot pipeline and open the maze on your laptop screen. See below.
- **kill_maze.sh** — Kill everything started by `run_maze_local.sh`. See below.

---

## run_maze_local.sh — Full pipeline launcher

Starts the entire stack and opens the maze UI on your laptop. Press **P** in the maze to enable AI autoplay — the robot will physically walk the maze.

### What it does

1. Starts the AI brain on the AI server (via `tmux`)
2. Starts `ros_bridge` HTTP server (port 5050) and `ros_bridge_node` on the Mini Pupper
3. Waits for `ros_bridge_node` to subscribe to Redis before proceeding
4. Starts a local brain proxy on `localhost:9001` — relays `/init` and `/next` to the real brain, and for each `/next` also forwards the action to the Pupper's `ros_bridge` so the robot moves in sync
5. Launches `maze/maze_sdl2` pointed at the proxy

### Requirements (one-time)

```bash
brew install sshpass
pip3 install fastapi uvicorn httpx
```

### Usage

```bash
bash scripts/run_maze_local.sh
```

### Controls

| Key | Action |
|-----|--------|
| Arrow keys / WASD | Manual play |
| P | Toggle AI autoplay (robot walks the maze) |
| L | Open dashboard |
| Q / Escape | Quit |

---

## kill_maze.sh — Tear everything down

Kills all processes started by `run_maze_local.sh`:

- Local brain proxy
- Local maze app
- Pupper `ros_bridge` + `ros_bridge_node`
- AI brain tmux session (`maze_brain2`)

### Usage

```bash
bash scripts/kill_maze.sh
```

---

---

## Team Build Instructions

### Quickstart (all platforms)
1. From the repo root:
   ```bash
   cd /path/to/abcapsp26TuThT1
   ```
2. Build:
   ```bash
   bash scripts/build.sh
   ```

`build.sh` compiles:
- `maze/maze_sdl2` (SDL2)
- `https/maze_https_mongo` (Mongo C driver)
- `https/maze_https_redis` (Redis)
- `https/maze_https_minipupper` (Mini-Pupper control)
- `dashboard/webview_dashboard` (optional, only if `webview` pkg-config module is installed)

### macOS (Intel + Apple Silicon)
1. Install Homebrew dependencies:
   ```bash
   brew install pkg-config sdl2 libcurl hiredis libmicrohttpd gnutls mongo-c-driver uuid
   ```
2. Optional (for embedded-like native webview window):
   ```bash
   brew install webview
   ```
3. Build:
   ```bash
   bash scripts/build.sh
   ```

Notes:
- macOS Homebrew installs can be different by architecture.
- `scripts/build.sh` includes macOS-specific logic to help `pkg-config` find the Mongo C driver (it may use `mongoc2` instead of `libmongoc-1.0` depending on what your Homebrew provides).

If you see a Mongo `pkg-config` error, run:
```bash
pkg-config --exists mongoc2 && echo "mongoc2 found" || echo "mongoc2 missing"
pkg-config --exists libmongoc-1.0 && echo "libmongoc-1.0 found" || echo "libmongoc-1.0 missing"
```

### Linux / Ubuntu
1. Install packages (Ubuntu/Debian):
   ```bash
   sudo apt-get update
   sudo apt-get install -y build-essential pkg-config \
     libsdl2-dev libcurl4-openssl-dev uuid-dev \
     libmicrohttpd-dev gnutls-bin libgnutls28-dev \
     libhiredis-dev \
     libmongoc-dev libbson-dev || true
   ```
2. If your distro uses different Mongo driver package names, also try:
   ```bash
   sudo apt-get install -y libmongoc-1.0-dev libbson-dev || true
   ```
3. Build:
   ```bash
   bash scripts/build.sh
   ```

Sanity check for Mongo:
```bash
pkg-config --exists mongoc2 && echo "mongoc2 found" || true
pkg-config --exists libmongoc-1.0 && echo "libmongoc-1.0 found" || true
```

### Windows
#### Recommended: build inside WSL (WSL1 or WSL2)
Build steps are the same inside WSL1 or WSL2 because they use the same Linux packages.

1. Install WSL (choose Ubuntu).
2. Open your WSL Ubuntu terminal.
3. Install Ubuntu build deps (same as Linux section above).
4. Build:
   ```bash
   bash scripts/build.sh
   ```

#### Running the SDL maze on Windows
- **WSL2 + WSLg** (recommended) is the easiest way to see the SDL2 window.
- If you're on **WSL1**, the build still works, but GUI may require an X server setup.
- Optional webview package name on Ubuntu/WSL may vary by distro (`webview`, `libwebview-dev`, or equivalent).

Maze runtime instructions (controls, dashboard behavior, autoplay, mTLS run commands) are in:
- `maze/README.md`


---

## Cross-Platform Verification Matrix (Team Checklist)

Run this exactly on each teammate machine and report pass/fail.

### 1) Build verification (all platforms)
From repo root:
```bash
bash scripts/build.sh
```

Expected:
- Build completes without stopping on compile errors.
- Binaries exist:
  - `maze/maze_sdl2`
  - `https/maze_https_redis`
  - `https/maze_https_minipupper`
- `https/maze_https_mongo` may be skipped if using:
  ```bash
  SKIP_HTTPS_MONGO=1 bash scripts/build.sh
  ```

### 2) Dashboard backend verification (all platforms)
Terminal A:
```bash
python -m uvicorn dashboard.main:app --host 127.0.0.1 --port 8443
```

Terminal B:
```bash
curl -s http://127.0.0.1:8443/recent?limit=5&page=1
curl -s http://127.0.0.1:8443/recent_missions?limit=5
curl -s http://127.0.0.1:8443/upstream_status
```

Expected:
- Each endpoint returns JSON.
- No backend crash after repeated `/upstream_status` polling.

### 3) Live ingest verification (all platforms)
Use this template:
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

Expected:
- Returns `{"ok":true}`.
- New move appears in dashboard telemetry table without manual page refresh.

### 4) Maze + dashboard verification
- Start `maze/maze_sdl2`.
- Press `L`.
- Validate behavior:
  - **macOS**: embedded full HTML dashboard appears inside the maze window.
  - **Linux/Ubuntu/WSL**: use browser fallback and confirm dashboard still updates live.

### 5) OS-specific success criteria
- **Mac Intel / Apple Silicon**
  - Build succeeds.
  - `L` embed works on macOS.
  - Live telemetry updates.
- **Ubuntu/Linux**
  - Build succeeds.
  - Maze runs; dashboard updates via browser fallback.
- **Windows (WSL1/WSL2)**
  - Build succeeds inside WSL.
  - With WSLg (or X server), maze renders.
  - Dashboard backend endpoints and ingest succeed.

---

### Common troubleshooting
1. **“Permission denied” when running scripts**
   ```bash
   chmod +x scripts/build.sh
   ```
2. **Mongo driver pkg-config not found**
   - If you just want to build the rest (maze + Redis + Mini-Pupper) without the Mongo logger right now:
     ```bash
     SKIP_HTTPS_MONGO=1 bash scripts/build.sh
     ```
   - Confirm the Mongo C driver `.pc` files exist (varies by OS):
     ```bash
     pkg-config --list-all | grep -i mongoc
     ```
   - If Mongo is missing, install the corresponding “Mongo C driver dev” package for your OS (see sections above).

---
