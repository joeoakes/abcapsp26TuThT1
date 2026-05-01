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
    REDIS_HOST          (default localhost)
    REDIS_PORT          (default 6379)
    MAZE_MOVE_ACK_TIMEOUT seconds to wait for ros_bridge_node completion (default 30)
    ROS_BRIDGE_PORT     informational only — uvicorn controls the actual port
"""

import asyncio
import os
import json
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REDIS_HOST    = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT    = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL = "maze_actions"
RESULT_CHANNEL = "maze_action_results"
ACK_TIMEOUT = float(os.getenv("MAZE_MOVE_ACK_TIMEOUT", "30.0"))

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
    duration: float = 0.0  # seconds the robot spent executing this move
    command_id: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}


def publish_and_wait_for_result(payload: dict, timeout_s: float) -> tuple[int, dict | None]:
    command_id = payload["command_id"]
    pubsub = r.pubsub(ignore_subscribe_messages=True)

    try:
        pubsub.subscribe(RESULT_CHANNEL)
        subscribers = r.publish(REDIS_CHANNEL, json.dumps(payload))
        log.info(
            "Published command_id=%s action=%s to %d subscriber(s) pos=(%s,%s)",
            command_id,
            payload.get("action"),
            subscribers,
            payload.get("x"),
            payload.get("y"),
        )

        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return subscribers, None

            message = pubsub.get_message(timeout=min(0.5, remaining))
            if not message or message.get("type") != "message":
                continue

            try:
                result = json.loads(message.get("data") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue

            if result.get("command_id") == command_id:
                return subscribers, result
    finally:
        try:
            pubsub.unsubscribe(RESULT_CHANNEL)
        finally:
            pubsub.close()


@app.post("/move", response_model=MoveResponse)
async def move(req: MoveRequest):
    action = req.action.strip().upper()

    if action not in VALID_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{action}'. Must be one of {sorted(VALID_ACTIONS)}"
        )

    payload = {
        "command_id": uuid.uuid4().hex,
        "action":     action,
        "session_id": req.session_id,
        "x":          req.x,
        "y":          req.y,
    }

    try:
        subscribers, result = await asyncio.to_thread(
            publish_and_wait_for_result,
            payload,
            ACK_TIMEOUT,
        )
    except redis.RedisError as exc:
        log.error("Redis publish/wait failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"Redis error: {exc}")

    if result is None:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Timed out waiting {ACK_TIMEOUT:.1f}s for robot ack "
                f"command_id={payload['command_id']} subscribers={subscribers}"
            ),
        )

    status = str(result.get("status") or "error")
    duration = float(result.get("duration") or 0.0)

    if status != "ok":
        raise HTTPException(
            status_code=502,
            detail=f"Robot reported status={status} command_id={payload['command_id']}",
        )

    log.info(
        "Move complete: command_id=%s action=%s duration=%.3fs",
        payload["command_id"],
        action,
        duration,
    )
    return MoveResponse(
        status=status,
        action=action,
        duration=duration,
        command_id=payload["command_id"],
    )
