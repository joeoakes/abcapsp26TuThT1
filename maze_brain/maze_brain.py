# maze_brain.py
import os
import json
from typing import Dict, List
import logging
import redis
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from rag_memory import maze_signature
from agents_langgraph import run_langgraph_step

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
ROBOT_BRIDGE_URL = os.getenv("ROBOT_BRIDGE_URL", "").strip()
ROBOT_BRIDGE_TIMEOUT_S = float(os.getenv("ROBOT_BRIDGE_TIMEOUT_S", "2.0"))
ROBOT_BRIDGE_REQUIRED = os.getenv("ROBOT_BRIDGE_REQUIRED", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maze_brain")

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
app = FastAPI()

class InitRequest(BaseModel):
    session_id: str
    width: int
    height: int
    cells: List[Dict[str, int]]
    start_x: int
    start_y: int
    goal_x: int
    goal_y: int

class NextRequest(BaseModel):
    session_id: str
    x: int
    y: int

class NextResponse(BaseModel):
    action: str

def forward_action_to_robot(session_id: str, x: int, y: int, action: str) -> None:
    """
    Forward AI action to the robot bridge when configured.
    This keeps maze_brain as the single decision source for both virtual and physical clients.
    """
    if not ROBOT_BRIDGE_URL:
        return

    payload = {
        "action": action,
        "session_id": session_id,
        "x": x,
        "y": y,
    }
    move_url = f"{ROBOT_BRIDGE_URL.rstrip('/')}/move"
    try:
        resp = requests.post(move_url, json=payload, timeout=ROBOT_BRIDGE_TIMEOUT_S)
        resp.raise_for_status()
        log.info("Forwarded action=%s session=%s pos=(%d,%d) to robot bridge", action, session_id, x, y)
    except Exception as exc:
        msg = f"Robot bridge forward failed ({move_url}): {exc}"
        if ROBOT_BRIDGE_REQUIRED:
            raise RuntimeError(msg) from exc
        log.warning(msg)

def store_maze_state(req: InitRequest):
    r.set(f"maze:{req.session_id}:width", req.width)
    r.set(f"maze:{req.session_id}:height", req.height)
    r.set(f"maze:{req.session_id}:start_x", req.start_x)
    r.set(f"maze:{req.session_id}:start_y", req.start_y)
    r.set(f"maze:{req.session_id}:goal_x", req.goal_x)
    r.set(f"maze:{req.session_id}:goal_y", req.goal_y)
    r.set(f"maze:{req.session_id}:cells", json.dumps(req.cells))

    sig = maze_signature(req.width, req.height, req.cells)
    r.set(f"maze:{req.session_id}:maze_sig", sig)

    # reset run memory
    r.delete(f"maze:{req.session_id}:visited")
    r.delete(f"maze:{req.session_id}:history")
    r.delete(f"maze:{req.session_id}:plan")
    r.delete(f"maze:{req.session_id}:plan_index")

    r.set(f"maze:{req.session_id}:history", json.dumps([]))
    r.set(f"maze:{req.session_id}:plan_index", 0)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/init")
def init_maze(req: InitRequest):
    try:
        store_maze_state(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok"}

@app.post("/next", response_model=NextResponse)
def next_move(req: NextRequest):
    # verify session exists
    if not r.get(f"maze:{req.session_id}:width"):
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        action = run_langgraph_step(req.session_id, req.x, req.y)
        forward_action_to_robot(req.session_id, req.x, req.y, action)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return NextResponse(action=action)
