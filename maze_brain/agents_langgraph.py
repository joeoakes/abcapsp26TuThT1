# agents_langgraph.py
import os
import json
from typing import Any, Dict, List, Optional, TypedDict, Literal

import redis
import requests

from langgraph.graph import StateGraph, END

from tools_maze import astar, analyze_maze, validate_plan, legal_moves, score_plan
from rag_memory import retrieve_experience, store_experience

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3")

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# ---------------------------
# LangGraph State
# ---------------------------

class MazeState(TypedDict, total=False):
    session_id: str
    width: int
    height: int
    cells: List[Dict[str,int]]

    start_x: int
    start_y: int
    goal_x: int
    goal_y: int

    x: int
    y: int

    visited: List[str]
    history: List[str]

    plan: List[str]
    plan_index: int

    need_plan: bool
    action: str
    reason: str

    maze_sig: str
    rag_context: List[str]

# ---------------------------
# Helpers
# ---------------------------

def _ollama(prompt: str) -> str:
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    last = None
    for _ in range(3):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
            resp.raise_for_status()
            return resp.json()["response"].strip()
        except Exception as exc:
            last = exc
    raise last

def _normalize_plan(raw: Any) -> List[str]:
    if isinstance(raw, list):
        out = []
        for x in raw:
            if isinstance(x, str):
                out.append(x.strip().upper())
            elif isinstance(x, dict) and "direction" in x:
                out.append(str(x["direction"]).strip().upper())
        # filter
        out = [m for m in out if m in ("UP","DOWN","LEFT","RIGHT")]
        return out
    return []

def _planner_prompt(s: MazeState) -> str:
    width, height = s["width"], s["height"]
    cells = s["cells"]
    x, y = s["x"], s["y"]
    gx, gy = s["goal_x"], s["goal_y"]
    visited = s.get("visited", [])
    history = s.get("history", [])
    rag_ctx = s.get("rag_context", [])

    maze_desc = ",".join(str(c["walls"]) for c in cells)
    legal = legal_moves(width, height, cells, x, y)

    tool_schema = """
You MUST respond with valid JSON only (no markdown, no extra text).

You are a Planner Agent. You can either:
A) Call a tool:
  {"type":"tool","name":"astar","args":{"start":[x,y],"goal":[gx,gy]}}
  {"type":"tool","name":"analyze_maze","args":{}}
  {"type":"tool","name":"validate_plan","args":{"plan":[...]}}

B) Return a full plan directly:
  {"type":"plan","plan":["RIGHT","DOWN",...]}
Rules:
- Plan must be from current position to goal.
- Only moves: UP DOWN LEFT RIGHT
- Prefer shortest plan.
- You may use tools to compute/validate before returning the plan.
"""

    rag_block = ""
    if rag_ctx:
        rag_block = "Retrieved prior experience (RAG):\n" + "\n---\n".join(rag_ctx) + "\n"

    return f"""{tool_schema}

Maze:
width={width}
height={height}
walls_bitmask: 1=N 2=E 4=S 8=W
cells_row_major_walls={maze_desc}

Current=({x},{y})
Goal=({gx},{gy})
LegalMovesFromCurrent={legal}

VisitedCount={len(visited)}
VisitedSample={visited[:40]}
HistoryTail={history[-40:]}

{rag_block}

Decide the best next step: either tool call(s) then a final plan.
Return JSON only.
"""

# ---------------------------
# Tool dispatcher for planner
# ---------------------------

def planner_agent_node(s: MazeState) -> MazeState:
    """
    LLM-first planner with tool use.
    It may call tools multiple times, then returns a plan.
    """
    width, height, cells = s["width"], s["height"], s["cells"]
    x, y = s["x"], s["y"]
    gx, gy = s["goal_x"], s["goal_y"]

    # Always compute a safe plan immediately so /next never stalls.
    fallback = astar(width, height, cells, (x, y), (gx, gy))
    if fallback:
        s["plan"] = fallback
        s["plan_index"] = 0
        s["need_plan"] = False
        s["reason"] = "fast_astar_plan"
        return s

    # RAG retrieval (maze-specific experience)
    query_text = f"maze plan from ({x},{y}) to ({gx},{gy}) with this walls grid"
    docs = retrieve_experience(s["maze_sig"], query_text, k=4)
    s["rag_context"] = []
    for d in docs:
        txt = d.get("text","")
        if txt:
            s["rag_context"].append(txt[:1200])

    # Planner loop: tool-call iterations then plan
    for _ in range(4):  # allow a few tool loops
        prompt = _planner_prompt(s)
        raw = _ollama(prompt)

        try:
            obj = json.loads(raw)
        except Exception:
            # If model fails JSON, force fallback to A*
            plan = astar(width, height, cells, (x,y), (gx,gy))
            s["plan"] = plan
            s["plan_index"] = 0
            s["need_plan"] = False
            s["reason"] = "planner_json_parse_failed_fallback_astar"
            return s

        if obj.get("type") == "tool":
            name = obj.get("name")
            args = obj.get("args", {}) or {}

            if name == "astar":
                start = tuple(args.get("start", [x,y]))
                goal = tuple(args.get("goal", [gx,gy]))
                plan = astar(width, height, cells, start, goal)
                # store tool result in state for the LLM to see
                s["tool_last_astar"] = plan  # type: ignore
                continue

            if name == "analyze_maze":
                analysis = analyze_maze(width, height, cells)
                s["tool_last_analysis"] = analysis  # type: ignore
                continue

            if name == "validate_plan":
                plan = args.get("plan", [])
                plan = _normalize_plan(plan)
                ok = validate_plan(plan, width, height, cells, x, y)
                s["tool_last_validation"] = {"ok": ok, "len": len(plan)}  # type: ignore
                continue

            # unknown tool -> ignore and continue
            continue

        if obj.get("type") == "plan":
            plan = _normalize_plan(obj.get("plan"))
            if not plan:
                # fallback A*
                plan = astar(width, height, cells, (x,y), (gx,gy))

            # validate
            if not validate_plan(plan, width, height, cells, x, y):
                # fallback A* if invalid
                plan = astar(width, height, cells, (x,y), (gx,gy))

            s["plan"] = plan
            s["plan_index"] = 0
            s["need_plan"] = False
            s["reason"] = "planner_returned_plan"
            return s

    # if loop exhausted, fallback A*
    plan = astar(width, height, cells, (x,y), (gx,gy))
    s["plan"] = plan
    s["plan_index"] = 0
    s["need_plan"] = False
    s["reason"] = "planner_tool_loop_exhausted_fallback_astar"
    return s

def executor_agent_node(s: MazeState) -> MazeState:
    """
    Executor agent:
    - uses stored plan+index
    - checks legality
    - tracks history/visited
    - triggers replanning if stuck/invalid/exhausted
    """
    width, height, cells = s["width"], s["height"], s["cells"]
    x, y = s["x"], s["y"]
    gx, gy = s["goal_x"], s["goal_y"]

    # goal check
    if x == gx and y == gy:
        s["action"] = "DONE"
        s["need_plan"] = False
        s["reason"] = "goal_reached"
        return s

    plan = s.get("plan") or []
    plan_index = int(s.get("plan_index") or 0)

    # if no plan, request one
    if not plan or plan_index >= len(plan):
        s["need_plan"] = True
        s["reason"] = "no_plan_or_exhausted"
        return s

    action = plan[plan_index]
    # verify legality at execution time (robust)
    legal = legal_moves(width, height, cells, x, y)
    if action not in legal:
        s["need_plan"] = True
        s["reason"] = f"illegal_next_step_{action}"
        return s

    # commit action
    s["action"] = action
    s["plan_index"] = plan_index + 1
    s["need_plan"] = False
    s["reason"] = "executed_step"
    return s

def should_plan(s: MazeState) -> Literal["planner", "end_exec"]:
    return "planner" if s.get("need_plan") else "end_exec"

# ---------------------------
# Build graph
# ---------------------------

def build_graph():
    g = StateGraph(MazeState)
    g.add_node("executor", executor_agent_node)
    g.add_node("planner", planner_agent_node)

    g.set_entry_point("executor")
    g.add_conditional_edges("executor", should_plan, {"planner": "planner", "end_exec": END})
    g.add_edge("planner", "executor")
    return g.compile()

GRAPH = build_graph()

# ---------------------------
# Redis persistence I/O
# ---------------------------

def load_session(session_id: str) -> MazeState:
    width  = int(r.get(f"maze:{session_id}:width") or 0)
    height = int(r.get(f"maze:{session_id}:height") or 0)
    gx = int(r.get(f"maze:{session_id}:goal_x") or 0)
    gy = int(r.get(f"maze:{session_id}:goal_y") or 0)
    sx = int(r.get(f"maze:{session_id}:start_x") or 0)
    sy = int(r.get(f"maze:{session_id}:start_y") or 0)
    cells = json.loads(r.get(f"maze:{session_id}:cells") or "[]")

    visited = list(r.smembers(f"maze:{session_id}:visited"))
    history = json.loads(r.get(f"maze:{session_id}:history") or "[]")
    plan = json.loads(r.get(f"maze:{session_id}:plan") or "[]")
    plan_index = int(r.get(f"maze:{session_id}:plan_index") or 0)
    maze_sig = r.get(f"maze:{session_id}:maze_sig") or ""

    return {
        "session_id": session_id,
        "width": width,
        "height": height,
        "cells": cells,
        "start_x": sx, "start_y": sy,
        "goal_x": gx, "goal_y": gy,
        "visited": visited,
        "history": history,
        "plan": plan,
        "plan_index": plan_index,
        "maze_sig": maze_sig,
    }

def save_plan(session_id: str, plan: List[str], plan_index: int) -> None:
    r.set(f"maze:{session_id}:plan", json.dumps(plan))
    r.set(f"maze:{session_id}:plan_index", plan_index)

def append_history(session_id: str, action: str) -> None:
    hist = json.loads(r.get(f"maze:{session_id}:history") or "[]")
    hist.append(action)
    if len(hist) > 5000:
        hist = hist[-5000:]
    r.set(f"maze:{session_id}:history", json.dumps(hist))

def add_visited(session_id: str, x: int, y: int) -> None:
    r.sadd(f"maze:{session_id}:visited", f"{x},{y}")

def store_success_experience(state: MazeState, final_plan: List[str]) -> None:
    # store an "experience doc" for RAG reuse
    analysis = analyze_maze(state["width"], state["height"], state["cells"])
    optimal = astar(state["width"], state["height"], state["cells"], (state["start_x"], state["start_y"]), (state["goal_x"], state["goal_y"]))
    sc = score_plan(final_plan, optimal)

    text = (
        f"Successful maze strategy.\n"
        f"MazeSig={state['maze_sig']}\n"
        f"Analysis={analysis}\n"
        f"PlanLen={len(final_plan)} OptimalLen={len(optimal)} Score={sc}\n"
        f"PlanHead={final_plan[:60]}\n"
        f"Notes: Follow the plan exactly. If illegal move occurs, replan with astar.\n"
    )
    store_experience({
        "maze_sig": state["maze_sig"],
        "text": text,
        "plan": final_plan,
        "meta": {"analysis": analysis, "score": sc},
    })

def run_langgraph_step(session_id: str, x: int, y: int) -> str:
    s = load_session(session_id)
    s["x"] = x
    s["y"] = y

    # visited update (persistent)
    add_visited(session_id, x, y)

    out = GRAPH.invoke(s)

    action = out.get("action", "DONE")
    reason = out.get("reason", "")

    # persist plan + plan_index changes
    if "plan" in out:
        save_plan(session_id, out.get("plan") or [], int(out.get("plan_index") or 0))

    # persist history (even DONE is useful)
    if action and action != "DONE":
        append_history(session_id, action)

    # if we are at start and just generated a plan, store RAG doc (optional)
    # also store on success if plan is optimal etc — your choice
    if reason.startswith("planner_") and out.get("plan"):
        # light experience store (optional)
        pass

    return action
