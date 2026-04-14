"""
ros_bridge.py
=============
Tiny FastAPI service — the HTTP side of the bridge.

maze_sdl2.c POSTs {"action":"RIGHT"} here.
This service validates the payload and publishes to Redis,
which ros_bridge_node.py subscribes to and converts to /cmd_vel.

Start with:
    uvicorn ros_bridge:app --host 0.0.0.0 --port 5050

Env vars:
    REDIS_HOST  (default localhost)
    REDIS_PORT  (default 6379)
    ROS_BRIDGE_PORT  informational only — uvicorn controls the actual port
"""

import os
import json
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REDIS_HOST    = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT    = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL = "maze:ros:move"

VALID_ACTIONS = {"UP", "DOWN", "LEFT", "RIGHT", "DONE"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ros_bridge")

# ---------------------------------------------------------------------------
# App + Redis
# ---------------------------------------------------------------------------
app = FastAPI(title="Maze → ROS Bridge")

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class MoveRequest(BaseModel):
    action: str           # "UP" | "DOWN" | "LEFT" | "RIGHT" | "DONE"
    session_id: str = ""  # forwarded for logging, not required
    x: int = 0
    y: int = 0


class MoveResponse(BaseModel):
    status: str
    action: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/move", response_model=MoveResponse)
def move(req: MoveRequest):
    action = req.action.strip().upper()

    if action not in VALID_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{action}'. Must be one of {sorted(VALID_ACTIONS)}"
        )

    if action == "DONE":
        log.info("DONE received — no movement published")
        return MoveResponse(status="done", action=action)

    payload = json.dumps({
        "action":     action,
        "session_id": req.session_id,
        "x":          req.x,
        "y":          req.y,
    })

    try:
        subscribers = r.publish(REDIS_CHANNEL, payload)
        log.info(f"Published action={action} to {subscribers} subscriber(s)  pos=({req.x},{req.y})")
    except redis.RedisError as exc:
        log.error(f"Redis publish failed: {exc}")
        raise HTTPException(status_code=503, detail=f"Redis error: {exc}")

    return MoveResponse(status="ok", action=action)
