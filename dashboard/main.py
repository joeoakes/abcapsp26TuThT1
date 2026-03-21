import asyncio
import datetime
import json
import os
import socket
import ssl
import time
import uuid
from typing import Any

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

connections: set[WebSocket] = set()
_last_pos_by_session_live: dict[str, tuple[int, int]] = {}

# Cache parsed telemetry / missions so repeated polling stays efficient.
_telemetry_cache: dict[str, Any] = {"mtime": None, "items": []}  # items are chronological
_missions_cache: dict[str, Any] = {"mtime": None, "items": []}  # items are mission summaries (already numbered)
_upstream_status_cache: dict[str, Any] = {"checked_at": 0.0, "value": None}


def _maze_moves_log_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "maze", "maze_moves.log"))


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v.strip() if isinstance(v, str) and v.strip() else default


LOGGING_HOST = _env("LOGGING_HOST", "10.170.8.130")
LOGGING_PORT = int(_env("LOGGING_PORT", "8443"))
AI_HOST = _env("AI_HOST", "10.170.8.109")
AI_PORT = int(_env("AI_PORT", "8443"))

# Generate a unique session ID for this run (used only for fallback simulation)
SESSION_ID = str(uuid.uuid4())

# Fallback simulation state (only used if no real telemetry is posted)
position = {"x": 0, "y": 0}
move_sequence = 0

# Function to generate telemetry JSON
def generate_telemetry(move_dir="stop"):
    global move_sequence, position
    move_sequence += 1

    # Update position for simulation (simple example)
    if move_dir == "forward":
        position["y"] += 1
    elif move_dir == "backward":
        position["y"] -= 1
    elif move_dir == "left":
        position["x"] -= 1
    elif move_dir == "right":
        position["x"] += 1

    return {
        "team": "team1tt",
        "event_type": "player_move",
        "input": {"device": "keyboard", "move_sequence": move_sequence},
        "player": {"position": position.copy()},
        "goal_reached": False,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "session_id": SESSION_ID,
        "move_dir": move_dir
    }


def _move_dir_from_delta(dx: int, dy: int) -> str:
    if dx == 0 and dy == 1:
        return "forward"
    if dx == 0 and dy == -1:
        return "backward"
    if dx == -1 and dy == 0:
        return "left"
    if dx == 1 and dy == 0:
        return "right"
    return "stop"


def _iter_json_objects_from_pretty_log(text: str):
    """
    Parse maze/maze_moves.log style content: many pretty-printed JSON objects,
    separated by blank lines.
    """
    buf: list[str] = []
    depth = 0
    in_obj = False
    for line in text.splitlines():
        if not in_obj:
            if "{" in line:
                in_obj = True
                depth = 0
                buf = []
            else:
                continue

        buf.append(line)
        depth += line.count("{") - line.count("}")
        if in_obj and depth == 0:
            raw = "\n".join(buf).strip()
            buf = []
            in_obj = False
            if raw:
                try:
                    yield json.loads(raw)
                except Exception:
                    # Skip malformed chunks
                    continue


def _tls_reachable(host: str, port: int, timeout_s: float = 1.5) -> dict[str, Any]:
    """
    Best-effort reachability check for an HTTPS server.
    We don't validate certificates here; this is only a connectivity indicator.
    """
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_s) as sock:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with ctx.wrap_socket(sock, server_hostname=host):
                pass
        return {
            "ok": True,
            "host": host,
            "port": port,
            "latency_ms": int((time.perf_counter() - start) * 1000),
        }
    except Exception as e:
        return {
            "ok": False,
            "host": host,
            "port": port,
            "error": str(e),
        }


@app.get("/upstream_status")
async def upstream_status():
    # Cache expensive TLS reachability checks to avoid overwhelming the API
    # when multiple dashboard clients poll at once.
    now = time.time()
    ttl_s = 5.0
    cached = _upstream_status_cache.get("value")
    checked_at = float(_upstream_status_cache.get("checked_at") or 0.0)
    if cached is not None and (now - checked_at) < ttl_s:
        return cached

    value = {
        "logging_server": _tls_reachable(LOGGING_HOST, LOGGING_PORT),
        "ai_server": _tls_reachable(AI_HOST, AI_PORT),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }
    _upstream_status_cache["checked_at"] = now
    _upstream_status_cache["value"] = value
    return value


@app.get("/recent")
async def recent(limit: int = 100, page: int = 1):
    """
    Return recent maze moves from maze/maze_moves.log, paged.

    - limit: items per page (default 100)
    - page:  1 = most recent page
    """
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500
    if page < 1:
        page = 1

    log_path = _maze_moves_log_path()
    if not os.path.exists(log_path):
        return JSONResponse(
            {"items": [], "limit": limit, "page": page, "total": 0, "path": log_path},
            status_code=200,
        )

    # Refresh cache only when the log changes.
    mtime = os.path.getmtime(log_path)
    if _telemetry_cache.get("mtime") != mtime or not _telemetry_cache.get("items"):
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        items: list[dict[str, Any]] = []
        last_pos_by_session: dict[str, tuple[int, int]] = {}

        for obj in _iter_json_objects_from_pretty_log(text):
            if not isinstance(obj, dict):
                continue

            session_id = str(obj.get("session_id", ""))
            pos = obj.get("player", {}).get("position", {})
            x = pos.get("x")
            y = pos.get("y")
            move_dir = obj.get("move_dir")
            if move_dir is None and isinstance(x, int) and isinstance(y, int) and session_id:
                prev = last_pos_by_session.get(session_id)
                if prev is not None:
                    dx = x - prev[0]
                    dy = y - prev[1]
                    move_dir = _move_dir_from_delta(dx, dy)
                else:
                    move_dir = "stop"
                last_pos_by_session[session_id] = (x, y)

            enriched = dict(obj)
            enriched.setdefault("team", "team1tt")
            if move_dir is not None:
                enriched["move_dir"] = move_dir
            items.append(enriched)

        _telemetry_cache["mtime"] = mtime
        _telemetry_cache["items"] = items

    items = _telemetry_cache["items"]
    total = len(items)
    end = total - (page - 1) * limit
    start = max(0, end - limit)
    page_items = items[start:end]
    page_items.reverse()  # most recent first

    return {"items": page_items, "limit": limit, "page": page, "total": total}


@app.get("/recent_missions")
async def recent_missions(limit: int = 20):
    """
    Build mission summaries from maze/maze_moves.log grouped by session_id.
    """
    # limit <= 0 means "all missions"
    if limit > 2000:
        limit = 2000

    log_path = _maze_moves_log_path()
    if not os.path.exists(log_path):
        return {"items": [], "limit": limit, "total": 0}

    # Cache missions so repeated polling stays efficient.
    mtime = os.path.getmtime(log_path)
    if _missions_cache.get("mtime") != mtime or not _missions_cache.get("items"):
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        missions: dict[str, dict[str, Any]] = {}
        last_pos_by_session: dict[str, tuple[int, int]] = {}

        for obj in _iter_json_objects_from_pretty_log(text):
            if not isinstance(obj, dict):
                continue
            if obj.get("event_type") != "player_move":
                continue
            session_id = str(obj.get("session_id") or "")
            if not session_id:
                continue

            ts = obj.get("timestamp")
            pos = obj.get("player", {}).get("position", {})
            x = pos.get("x")
            y = pos.get("y")
            move_dir = obj.get("move_dir")
            if move_dir is None and isinstance(x, int) and isinstance(y, int):
                prev = last_pos_by_session.get(session_id)
                if prev is not None:
                    move_dir = _move_dir_from_delta(x - prev[0], y - prev[1])
                else:
                    move_dir = "stop"
                last_pos_by_session[session_id] = (x, y)

            m = missions.get(session_id)
            if m is None:
                m = {
                    "session_id": session_id,
                    "start_time": ts,
                    "end_time": ts,
                    "moves_total": 0,
                    "moves_left_turn": 0,
                    "moves_right_turn": 0,
                    "moves_straight": 0,
                    "moves_reverse": 0,
                    "goal_reached": False,
                }
                missions[session_id] = m

            m["moves_total"] += 1
            m["end_time"] = ts or m["end_time"]
            if move_dir == "left":
                m["moves_left_turn"] += 1
            elif move_dir == "right":
                m["moves_right_turn"] += 1
            elif move_dir == "forward":
                m["moves_straight"] += 1
            elif move_dir in ("reverse", "backward"):
                m["moves_reverse"] += 1

            if obj.get("goal_reached") is True:
                m["goal_reached"] = True

        all_items = list(missions.values())
        # Ascending first so mission IDs increase over time (MISSION_001 oldest).
        all_items.sort(key=lambda m: str(m.get("end_time") or ""))
        for i, m in enumerate(all_items, start=1):
            m["mission_id"] = f"MISSION_{i:03d}"
            m["distance_traveled"] = float(m["moves_total"])

        # Then display descending (newest first).
        items = list(reversed(all_items))

        # Identify the newest non-success mission as "in_progress";
        # older non-success missions are treated as "aborted".
        newest_non_success_idx = None
        for idx, m in enumerate(items):
            if not m.get("goal_reached"):
                newest_non_success_idx = idx
                break

        for idx, m in enumerate(items):
            if m.get("goal_reached"):
                m["mission_result"] = "success"
            elif newest_non_success_idx is not None and idx == newest_non_success_idx:
                m["mission_result"] = "in_progress"
            else:
                m["mission_result"] = "aborted"

        _missions_cache["mtime"] = mtime
        _missions_cache["items"] = items

    items = _missions_cache["items"]
    if limit > 0:
        items = items[:limit]

    return {"items": items, "limit": limit, "total": len(_missions_cache.get("items", []))}


@app.post("/ingest")
async def ingest(payload: dict[str, Any]):
    """
    Receive real telemetry (from mini-pupper, maze server, etc.) and broadcast it
    to all connected dashboard WebSocket clients.
    """
    # If move_dir is missing (common for the /move template), infer it from (x,y) delta.
    session_id = str(payload.get("session_id") or "")
    pos = payload.get("player", {}).get("position", {}) if isinstance(payload.get("player"), dict) else {}
    x = pos.get("x")
    y = pos.get("y")
    if payload.get("move_dir") is None and session_id and isinstance(x, int) and isinstance(y, int):
        prev = _last_pos_by_session_live.get(session_id)
        payload = dict(payload)
        if prev is not None:
            payload["move_dir"] = _move_dir_from_delta(x - prev[0], y - prev[1])
        else:
            payload["move_dir"] = "stop"
        _last_pos_by_session_live[session_id] = (x, y)

    dead: list[WebSocket] = []
    for ws in list(connections):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connections.discard(ws)

    return JSONResponse({"status": "ok", "subscribers": len(connections)})


# Alias to match the existing maze server template name.
@app.post("/move")
async def move(payload: dict[str, Any]):
    return await ingest(payload)


# WebSocket endpoint
@app.websocket("/telemetry")
async def telemetry_ws(websocket: WebSocket):
    await websocket.accept()
    connections.add(websocket)
    try:
        while True:
            # Keep the socket open; data is pushed via POST /ingest.
            # Send a lightweight heartbeat so proxies/clients don't time out.
            await websocket.send_json(
                {
                    "event_type": "heartbeat",
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                }
            )
            await asyncio.sleep(20)
    except Exception as e:
        print("WebSocket closed:", e)
    finally:
        connections.discard(websocket)