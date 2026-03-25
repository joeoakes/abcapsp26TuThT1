import os
import json
from typing import Dict, List
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import traceback
from rag_memory import maze_signature
from agents_langchain import run_brain_step

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

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
    r.delete(f"maze:{req.session_id}:stuck_count")

    r.set(f"maze:{req.session_id}:history", json.dumps([]))
    r.set(f"maze:{req.session_id}:plan", json.dumps([]))
    r.set(f"maze:{req.session_id}:plan_index", 0)
    r.set(f"maze:{req.session_id}:stuck_count", 0)


@app.post("/init")
def init_maze(req: InitRequest):
    try:
        store_maze_state(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok"}


@app.post("/next", response_model=NextResponse)
def next_move(req: NextRequest):
    if not r.get(f"maze:{req.session_id}:width"):
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        action = run_brain_step(req.session_id, req.x, req.y)
        return NextResponse(action=action)
    except Exception as exc:
        print("\n=== /next crashed ===")
        print(f"session_id={req.session_id} x={req.x} y={req.y}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc))
