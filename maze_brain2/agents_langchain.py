import os
import json
import time
from typing import Any, Dict, List, Tuple, Optional
from collections import deque

import redis
import requests

from tools_maze import validate_plan, legal_moves
from rag_memory import retrieve_experience, store_experience


# ============================================================
# Config (FAST PATH FIRST, escape only when stuck)
# ============================================================

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Ollama generate endpoint (MUST include /api/generate)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3")

# Fast planning knobs
MAX_PLAN_LEN = int(os.getenv("MAX_PLAN_LEN", "8"))          # keep small -> fast
OLLAMA_TIMEOUT_S = float(os.getenv("OLLAMA_TIMEOUT_S", "8"))  # keep low -> responsive
LLM_NUM_PREDICT = int(os.getenv("LLM_NUM_PREDICT", "96"))  # cap output tokens
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_CONNECT_TIMEOUT_S = float(os.getenv("LLM_CONNECT_TIMEOUT_S", "0.7"))
LLM_READ_TIMEOUT_S    = float(os.getenv("LLM_READ_TIMEOUT_S", "1.8"))

# Loop/stuck detection knobs (ONLY trigger escape when strong evidence)
LOOP_WINDOW = int(os.getenv("LOOP_WINDOW", "24"))
STAGNATION_STEPS = int(os.getenv("STAGNATION_STEPS", "24"))   # no best-distance improvement
TWO_CYCLE_CHECK = os.getenv("TWO_CYCLE_CHECK", "1").strip() == "1"

# Escape knobs (runs only on stuck)
ESCAPE_BFS_MAX_DEPTH = int(os.getenv("ESCAPE_BFS_MAX_DEPTH", "14"))
TABU_WINDOW = int(os.getenv("TABU_WINDOW", "12"))             # avoid bouncing back during escape
TABOO_EDGE_TTL_STEPS = int(os.getenv("TABOO_EDGE_TTL_STEPS", "30"))  # only used on stuck

# Rate limit LLM calls (prevents runaway slowdowns)
MAX_LLM_CALLS_PER_60S = int(os.getenv("MAX_LLM_CALLS_PER_60S", "10"))

# Optional RAG (OFF by default for speed)
ENABLE_RAG = os.getenv("ENABLE_RAG", "0").strip() == "1"

MAX_HISTORY = int(os.getenv("MAX_HISTORY", "5000"))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

VALID_MOVES = ("UP", "DOWN", "LEFT", "RIGHT")
DELTAS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


# ============================================================
# Small helpers
# ============================================================

def manhattan(x: int, y: int, gx: int, gy: int) -> int:
    return abs(x - gx) + abs(y - gy)

def get_escape_cooldown(session_id: str) -> int:
    return int(r.get(f"maze:{session_id}:escape_cd") or 0)

def set_escape_cooldown(session_id: str, v: int) -> None:
    r.set(f"maze:{session_id}:escape_cd", int(v))


def next_pos(x: int, y: int, move: str) -> Tuple[int, int]:
    dx, dy = DELTAS[move]
    return x + dx, y + dy


def normalize_plan(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, dict) and "plan" in raw:
        raw = raw.get("plan")
    if isinstance(raw, list):
        out: List[str] = []
        for v in raw:
            if isinstance(v, str):
                out.append(v.strip().upper())
            elif isinstance(v, dict) and "direction" in v:
                out.append(str(v["direction"]).strip().upper())
        return [m for m in out if m in VALID_MOVES]
    return []


# ============================================================
# Redis persistence
# ============================================================

def load_session(session_id: str) -> Dict[str, Any]:
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
        "start_x": sx,
        "start_y": sy,
        "goal_x": gx,
        "goal_y": gy,
        "visited": visited,
        "history": history,
        "plan": plan,
        "plan_index": plan_index,
        "maze_sig": maze_sig,
    }


def save_plan(session_id: str, plan: List[str], plan_index: int) -> None:
    r.set(f"maze:{session_id}:plan", json.dumps(plan))
    r.set(f"maze:{session_id}:plan_index", int(plan_index))


def append_history(session_id: str, action: str) -> None:
    key = f"maze:{session_id}:history"
    hist = json.loads(r.get(key) or "[]")
    hist.append(action)
    if len(hist) > MAX_HISTORY:
        hist = hist[-MAX_HISTORY:]
    r.set(key, json.dumps(hist))


def add_visited(session_id: str, x: int, y: int) -> None:
    r.sadd(f"maze:{session_id}:visited", f"{x},{y}")


def get_last_positions(session_id: str, n: int) -> List[str]:
    arr = json.loads(r.get(f"maze:{session_id}:pos_history") or "[]")
    return arr[-n:]


def get_recent_positions(session_id: str, window: int) -> List[str]:
    return get_last_positions(session_id, window)


def append_position(session_id: str, x: int, y: int) -> None:
    key = f"maze:{session_id}:pos_history"
    arr = json.loads(r.get(key) or "[]")
    arr.append(f"{x},{y}")
    if len(arr) > MAX_HISTORY:
        arr = arr[-MAX_HISTORY:]
    r.set(key, json.dumps(arr))


# Parent pointers (for cheap backtrack escape)
def set_parent(session_id: str, child_x: int, child_y: int, parent_x: int, parent_y: int) -> None:
    r.hset(f"maze:{session_id}:parent", f"{child_x},{child_y}", f"{parent_x},{parent_y}")


def get_parent(session_id: str, x: int, y: int) -> Optional[str]:
    return r.hget(f"maze:{session_id}:parent", f"{x},{y}")


# Best-distance tracking (stagnation detector)
def get_best_dist(session_id: str) -> int:
    return int(r.get(f"maze:{session_id}:best_dist") or 10**9)


def set_best_dist(session_id: str, d: int) -> None:
    r.set(f"maze:{session_id}:best_dist", int(d))


def get_last_improve_step(session_id: str) -> int:
    return int(r.get(f"maze:{session_id}:last_improve_step") or 0)


def set_last_improve_step(session_id: str, step: int) -> None:
    r.set(f"maze:{session_id}:last_improve_step", int(step))


# Taboo edges (ONLY used after we detect stuck, not in normal path)
def taboo_key(session_id: str) -> str:
    return f"maze:{session_id}:taboo_edges"  # hash edge_id -> expire_step(int)


def edge_id(x: int, y: int, move: str) -> str:
    nx, ny = next_pos(x, y, move)
    return f"{x},{y}->{nx},{ny}"


def cleanup_taboo(session_id: str, cur_step: int) -> None:
    tb = r.hgetall(taboo_key(session_id)) or {}
    for e, exp in tb.items():
        try:
            if int(exp) <= cur_step:
                r.hdel(taboo_key(session_id), e)
        except Exception:
            r.hdel(taboo_key(session_id), e)


def taboo_edge(session_id: str, x: int, y: int, move: str, cur_step: Optional[int] = None) -> None:
    if cur_step is None:
        cur_step = len(json.loads(r.get(f"maze:{session_id}:history") or "[]"))
    exp = cur_step + TABOO_EDGE_TTL_STEPS
    r.hset(taboo_key(session_id), edge_id(x, y, move), exp)


def is_edge_taboo(session_id: str, x: int, y: int, move: str, cur_step: Optional[int] = None) -> bool:
    if cur_step is None:
        cur_step = len(json.loads(r.get(f"maze:{session_id}:history") or "[]"))
    cleanup_taboo(session_id, cur_step)
    return r.hexists(taboo_key(session_id), edge_id(x, y, move))

# LLM rate limit
def llm_budget_ok(session_id: str) -> bool:
    key = f"maze:{session_id}:llm_calls_ts"
    now = int(time.time())
    arr = json.loads(r.get(key) or "[]")
    arr = [t for t in arr if now - t <= 60]
    ok = len(arr) < MAX_LLM_CALLS_PER_60S
    if ok:
        arr.append(now)
    r.set(key, json.dumps(arr))
    return ok


# ============================================================
# Deterministic fallback (fast)
# ============================================================

def choose_move_prefer_unvisited(width: int, height: int, cells: List[Dict[str, int]],
                                 x: int, y: int, gx: int, gy: int,
                                 visited: List[str]) -> str:
    legal = legal_moves(width, height, cells, x, y)
    if not legal:
        return "DONE"

    visited_set = set(visited)
    scored: List[Tuple[int, int, str]] = []

    for m in legal:
        nx, ny = next_pos(x, y, m)
        is_visited = 1 if f"{nx},{ny}" in visited_set else 0  # 0 better
        dist = manhattan(nx, ny, gx, gy)
        scored.append((is_visited, dist, m))

    scored.sort(key=lambda t: (t[0], t[1]))
    return scored[0][2]


# ============================================================
# Stuck / loop detection (cheap)
# ============================================================

def is_two_cycle(session_id: str) -> bool:
    # pattern A,B,A,B in last 4 positions
    last4 = get_last_positions(session_id, 4)
    return (
        len(last4) == 4 and
        last4[0] == last4[2] and
        last4[1] == last4[3] and
        last4[0] != last4[1]
    )


def should_escape(session_id: str, x: int, y: int, cur_step: int) -> Tuple[bool, str]:
    """
    STRICT stuck detector to avoid slowing the normal path.
    Returns (True, reason) only when strongly stuck.
    """
    # two-cycle is a very strong stuck signal and cheap
    if TWO_CYCLE_CHECK and is_two_cycle(session_id):
        return True, "two_cycle"

    recent = get_last_positions(session_id, LOOP_WINDOW)
    if len(recent) >= LOOP_WINDOW:
        cur = f"{x},{y}"
        # repeated current cell many times recently
        if recent.count(cur) >= 3:
            return True, "repeat_cell"
        # bouncing among very few cells
        if len(set(recent)) <= max(3, LOOP_WINDOW // 4):
            return True, "low_unique_positions"

    # stagnation based on best manhattan distance seen
    last_improve = get_last_improve_step(session_id)
    if cur_step - last_improve >= STAGNATION_STEPS:
        return True, "stagnation"

    return False, ""

def should_replan_for_loop(session_id: str, x: int, y: int) -> bool:
    """
    Lightweight loop detector used by executor_decide.
    (This keeps the old call-site working.)
    """
    recent = get_last_positions(session_id, LOOP_WINDOW)
    if len(recent) < LOOP_WINDOW:
        return False

    cur = f"{x},{y}"
    if recent.count(cur) >= 3:
        return True

    if len(set(recent)) <= max(3, LOOP_WINDOW // 4):
        return True

    return False

# ============================================================
# Escape logic (ONLY called when stuck)
# ============================================================

def has_unvisited_neighbor(width: int, height: int, cells: List[Dict[str, int]],
                           x: int, y: int, visited_set: set) -> bool:
    for m in legal_moves(width, height, cells, x, y):
        nx, ny = next_pos(x, y, m)
        if f"{nx},{ny}" not in visited_set:
            return True
    return False


def bfs_escape_one_move(session_id: str,
                        width: int, height: int, cells: List[Dict[str, int]],
                        x: int, y: int,
                        visited: List[str],
                        cur_step: int,
                        max_depth: int) -> Optional[str]:
    """
    Micro-escape BFS:
      - searches up to max_depth
      - target = nearest 'frontier' cell (has an unvisited neighbor)
      - avoids recent-taboo edges (only relevant after stuck)
      - avoids stepping into last TABU_WINDOW positions when possible
      - returns ONLY the first move toward that frontier
    """
    visited_set = set(visited)
    if has_unvisited_neighbor(width, height, cells, x, y, visited_set):
        return None  # already at a frontier, no need BFS

    tabu_positions = set(get_last_positions(session_id, TABU_WINDOW))
    start = (x, y)
    q = deque([(start, [])])
    seen = {start}

    while q:
        (cx, cy), path = q.popleft()
        if len(path) >= max_depth:
            continue

        for m in legal_moves(width, height, cells, cx, cy):
            # avoid taboo edges if set (only when stuck)
            if is_edge_taboo(session_id, cx, cy, m, cur_step):
                continue

            nx, ny = next_pos(cx, cy, m)
            nxt = (nx, ny)
            if nxt in seen:
                continue

            # soft-avoid bouncing into very recent positions
            if f"{nx},{ny}" in tabu_positions and len(path) < 2:
                # allow later, but prefer not immediately
                continue

            npath = path + [m]

            if has_unvisited_neighbor(width, height, cells, nx, ny, visited_set):
                return npath[0] if npath else None

            seen.add(nxt)
            q.append((nxt, npath))

    return None


def escape_move(s: Dict[str, Any], x: int, y: int, cur_step: int) -> str:
    """
    Choose one escape move; try BFS frontier, else parent backtrack, else local unvisited.
    """
    session_id = s["session_id"]
    width, height, cells = s["width"], s["height"], s["cells"]
    gx, gy = s["goal_x"], s["goal_y"]
    visited = s.get("visited", [])
    visited_set = set(visited)

    # 1) micro-BFS to nearest frontier
    m = bfs_escape_one_move(session_id, width, height, cells, x, y, visited, cur_step, ESCAPE_BFS_MAX_DEPTH)
    if m:
        return m

    # 2) parent backtrack (cheap)
    parent = get_parent(session_id, x, y)
    if parent:
        px, py = map(int, parent.split(","))
        for mv in legal_moves(width, height, cells, x, y):
            nx, ny = next_pos(x, y, mv)
            if nx == px and ny == py:
                return mv

    # 3) local deterministic (prefer unvisited)
    return choose_move_prefer_unvisited(width, height, cells, x, y, gx, gy, visited)


# ============================================================
# LLM (fast, bounded) + planner prompt
# ============================================================

def llm_invoke(prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": LLM_TEMPERATURE,
            "top_p": 0.9,
            "num_predict": 64,     # <<< MUCH smaller output
        },
    }

    # MUCH tighter timeout so /next never hangs
    resp = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=(LLM_CONNECT_TIMEOUT_S, LLM_READ_TIMEOUT_S),
    )
    resp.raise_for_status()
    data = resp.json()
    return (data.get("response") or "").strip()

def build_planner_prompt(s: Dict[str, Any], x: int, y: int) -> str:
    width, height = s["width"], s["height"]
    cells = s["cells"]
    gx, gy = s["goal_x"], s["goal_y"]

    legal = legal_moves(width, height, cells, x, y)

    # local walls only (cheap + enough for short-horizon planning)
    def safe_cell_walls(px: int, py: int) -> Optional[int]:
        if px < 0 or py < 0 or px >= width or py >= height:
            return None
        return cells[py * width + px]["walls"]

    local = {
        "cur": safe_cell_walls(x, y),
        "up": safe_cell_walls(x, y - 1),
        "down": safe_cell_walls(x, y + 1),
        "left": safe_cell_walls(x - 1, y),
        "right": safe_cell_walls(x + 1, y),
    }

    # keep tiny “tabu” memory (last few positions)
    tabu = get_last_positions(s["session_id"], 10)

    return f"""You are a maze planner.
Reply with VALID JSON ONLY. No extra text.

Allowed moves: ["UP","DOWN","LEFT","RIGHT"].
You must choose a SHORT plan chunk.

Constraints:
- plan length <= {MAX_PLAN_LEN}
- first move MUST be in legal_moves_from_current
- avoid returning to recent positions if possible

State:
current=({x},{y})
goal=({gx},{gy})
legal_moves_from_current={legal}
local_walls_bitmask={json.dumps(local)}
recent_positions={tabu}

Output JSON exactly:
{{"plan":["RIGHT","DOWN"],"reason":"..."}}"""


def llm_plan_chunk(s: Dict[str, Any], x: int, y: int) -> Tuple[List[str], str]:
    width, height, cells = s["width"], s["height"], s["cells"]
    gx, gy = s["goal_x"], s["goal_y"]

    if x == gx and y == gy:
        return ([], "already_at_goal")

    prompt = build_planner_prompt(s, x, y)

    try:
        raw = llm_invoke(prompt)
    except Exception as e:
        mv = choose_move_prefer_unvisited(width, height, cells, x, y, gx, gy, s.get("visited", []))
        return ([mv] if mv != "DONE" else [], f"llm_error:{type(e).__name__}")

    try:
        obj = json.loads(raw)
    except Exception:
        mv = choose_move_prefer_unvisited(width, height, cells, x, y, gx, gy, s.get("visited", []))
        return ([mv] if mv != "DONE" else [], "llm_non_json")

    plan = normalize_plan(obj)
    reason = str(obj.get("reason", ""))[:200] if isinstance(obj, dict) else ""

    if not plan:
        mv = choose_move_prefer_unvisited(width, height, cells, x, y, gx, gy, s.get("visited", []))
        return ([mv] if mv != "DONE" else [], "llm_empty_plan")

    # validate walls/bounds (short plan so this is cheap)
    if not validate_plan(plan, width, height, cells, x, y):
        mv = choose_move_prefer_unvisited(width, height, cells, x, y, gx, gy, s.get("visited", []))
        return ([mv] if mv != "DONE" else [], "llm_invalid_plan")

    # first move must be legal now
    legal_now = legal_moves(width, height, cells, x, y)
    if plan[0] not in legal_now:
        mv = choose_move_prefer_unvisited(width, height, cells, x, y, gx, gy, s.get("visited", []))
        return ([mv] if mv != "DONE" else [], "llm_first_move_illegal")

    return (plan[:MAX_PLAN_LEN], reason or "llm_ok")

def llm_plan(s: Dict[str, Any], x: int, y: int) -> Tuple[List[str], str]:
    return llm_plan_chunk(s, x, y)
# ============================================================
# Executor decision (FAST PATH)
# ============================================================

def mark_edge_used(session_id: str, x: int, y: int, move: str) -> None:
    key = f"maze:{session_id}:edge_hist"
    arr = json.loads(r.get(key) or "[]")
    arr.append(edge_id(x, y, move))
    if len(arr) > 200:   # keep tiny for speed
        arr = arr[-200:]
    r.set(key, json.dumps(arr))


def should_taboo_repeated_edge(session_id: str, x: int, y: int, move: str) -> bool:
    """
    Only used to stop ABAB bouncing. Tiny recent window for speed.
    """
    key = f"maze:{session_id}:edge_hist"
    arr = json.loads(r.get(key) or "[]")
    arr = arr[-30:]
    e = edge_id(x, y, move)
    return arr.count(e) >= 3


def local_pick_move(session_id: str,
                    width: int, height: int, cells: List[Dict[str, int]],
                    x: int, y: int,
                    gx: int, gy: int,
                    visited: List[str]) -> Optional[str]:
    """
    Fast deterministic local policy:
    - prefer unvisited neighbors
    - tie-break by distance to goal
    - avoid taboo edges if possible
    """
    legal = legal_moves(width, height, cells, x, y)
    if not legal:
        return None

    visited_set = set(visited)
    scored = []
    for m in legal:
        nx, ny = next_pos(x, y, m)
        unvisited = 1 if f"{nx},{ny}" not in visited_set else 0
        taboo = 1 if is_edge_taboo(session_id, x, y, m) else 0
        dist = manhattan(nx, ny, gx, gy)
        scored.append((-unvisited, taboo, dist, m))  # lower is better overall

    scored.sort()
    return scored[0][3]


def executor_decide(s: Dict[str, Any], x: int, y: int) -> Tuple[str, str]:
    """
    FAST PATH:
      1) Follow existing plan as long as next step is legal and not taboo.
      2) Only ESCAPE when clearly looping/stuck.
      3) Only REPLAN when plan missing/exhausted or after escape cooldown.
    """
    session_id = s["session_id"]
    width, height, cells = s["width"], s["height"], s["cells"]
    gx, gy = s["goal_x"], s["goal_y"]
    visited = s.get("visited", [])
    visited_set = set(visited)

    if x == gx and y == gy:
        return ("DONE", "goal_reached")

    # If we are in escape cooldown, do NOT trigger LLM replans
    if get_escape_cooldown(session_id) > 0:
        return ("LOCAL", "escape_cooldown_local_move")

    # Strong loop signals ONLY
    if is_two_cycle(session_id) or should_replan_for_loop(session_id, x, y):
        return ("ESCAPE", "loop_detected")

    # If no frontier here and revisiting same cell -> escape
    recent = get_recent_positions(session_id, LOOP_WINDOW)
    if (not has_unvisited_neighbor(width, height, cells, x, y, visited_set)
        and recent.count(f"{x},{y}") >= 2):
        return ("ESCAPE", "dead_pocket_revisit")

    # Plan-first execution (this is why it used to be fast)
    plan: List[str] = s.get("plan") or []
    plan_index: int = int(s.get("plan_index") or 0)

    if plan and plan_index < len(plan):
        nxt = plan[plan_index]
        legal_now = legal_moves(width, height, cells, x, y)
        if nxt in legal_now and not is_edge_taboo(session_id, x, y, nxt):
            return (nxt, "follow_plan")
        return ("REPLAN", f"plan_step_bad:{nxt}")

    # No plan -> REPLAN (LLM primary, but guarded by budget/timeouts)
    return ("REPLAN", "no_plan_or_exhausted")

# ============================================================
# Main entry: called by FastAPI /next
# ============================================================

def run_brain_step(session_id: str, x: int, y: int) -> str:
    s = load_session(session_id)
    s["session_id"] = session_id

    # Persist position + visited
    append_position(session_id, x, y)
    add_visited(session_id, x, y)

    width, height, cells = s["width"], s["height"], s["cells"]
    gx, gy = s["goal_x"], s["goal_y"]
    visited = s.get("visited", [])

    action, reason = executor_decide(s, x, y)

    if action == "DONE":
        return "DONE"

    # -------------------------
    # ESCAPE: ONE micro-BFS step, then short LOCAL cooldown (NO LLM)
    # -------------------------
    if action == "ESCAPE":
        cur_step = len(json.loads(r.get(f"maze:{session_id}:history") or "[]"))

        move = bfs_escape_one_move(
            session_id=session_id,
            width=width,
            height=height,
            cells=cells,
            x=x,
            y=y,
            visited=visited,
            cur_step=cur_step,
            max_depth=ESCAPE_BFS_MAX_DEPTH,
        )

        if move is None:
            move = local_pick_move(session_id, width, height, cells, x, y, gx, gy, visited)

        if not move:
            return "DONE"

        # discourage repeating edges
        if should_taboo_repeated_edge(session_id, x, y, move):
            taboo_edge(session_id, x, y, move)  # cur_step optional in your fixed version

        # clear plan, but DO NOT replan immediately — cooldown makes it fast
        save_plan(session_id, [], 0)
        set_escape_cooldown(session_id, 3)

        # record + edge history
        append_history(session_id, move)
        mark_edge_used(session_id, x, y, move)

        # set parent pointer for backtracking escape (best-effort)
        try:
            nx, ny = next_pos(x, y, move)
            set_parent(session_id, nx, ny, x, y)
        except Exception:
            pass

        return move

    # -------------------------
    # LOCAL (escape cooldown): deterministic, instant moves
    # -------------------------
    if action == "LOCAL":
        cd = get_escape_cooldown(session_id)
        if cd > 0:
            set_escape_cooldown(session_id, cd - 1)

        move = local_pick_move(session_id, width, height, cells, x, y, gx, gy, visited)
        if not move:
            return "DONE"

        if should_taboo_repeated_edge(session_id, x, y, move):
            taboo_edge(session_id, x, y, move)

        append_history(session_id, move)
        mark_edge_used(session_id, x, y, move)

        # parent pointer
        try:
            nx, ny = next_pos(x, y, move)
            set_parent(session_id, nx, ny, x, y)
        except Exception:
            pass

        return move

    # -------------------------
    # REPLAN: call LLM only if budget allows; otherwise local fallback
    # -------------------------
    if action == "REPLAN":
        # prevent LLM spam
        if not llm_budget_ok(session_id):
            move = local_pick_move(session_id, width, height, cells, x, y, gx, gy, visited)
            if not move:
                return "DONE"
            append_history(session_id, move)
            mark_edge_used(session_id, x, y, move)
            try:
                nx, ny = next_pos(x, y, move)
                set_parent(session_id, nx, ny, x, y)
            except Exception:
                pass
            return move

        new_plan, _ = llm_plan(s, x, y)

        if not new_plan:
            move = local_pick_move(session_id, width, height, cells, x, y, gx, gy, visited)
            if not move:
                return "DONE"
            append_history(session_id, move)
            mark_edge_used(session_id, x, y, move)
            try:
                nx, ny = next_pos(x, y, move)
                set_parent(session_id, nx, ny, x, y)
            except Exception:
                pass
            return move

        # Save plan and execute first step immediately (fast)
        first = new_plan[0]
        save_plan(session_id, new_plan, 1)

        # If first move is taboo/repeating, override locally
        if is_edge_taboo(session_id, x, y, first) or should_taboo_repeated_edge(session_id, x, y, first):
            taboo_edge(session_id, x, y, first)
            move = local_pick_move(session_id, width, height, cells, x, y, gx, gy, visited)
            if move:
                save_plan(session_id, [], 0)
                append_history(session_id, move)
                mark_edge_used(session_id, x, y, move)
                try:
                    nx, ny = next_pos(x, y, move)
                    set_parent(session_id, nx, ny, x, y)
                except Exception:
                    pass
                return move

        append_history(session_id, first)
        mark_edge_used(session_id, x, y, first)
        try:
            nx, ny = next_pos(x, y, first)
            set_parent(session_id, nx, ny, x, y)
        except Exception:
            pass
        return first

    # -------------------------
    # Normal move: follow plan (FAST path)
    # -------------------------
    plan = s.get("plan") or []
    plan_index = int(s.get("plan_index") or 0)

    if should_taboo_repeated_edge(session_id, x, y, action):
        taboo_edge(session_id, x, y, action)

    save_plan(session_id, plan, plan_index + 1)
    append_history(session_id, action)
    mark_edge_used(session_id, x, y, action)

    # update best-distance + stagnation bookkeeping
    try:
        cur_step = len(json.loads(r.get(f"maze:{session_id}:history") or "[]"))
        d = manhattan(x, y, gx, gy)
        best = get_best_dist(session_id)
        if d < best:
            set_best_dist(session_id, d)
            set_last_improve_step(session_id, cur_step)
    except Exception:
        pass

    # parent pointer
    try:
        nx, ny = next_pos(x, y, action)
        set_parent(session_id, nx, ny, x, y)
    except Exception:
        pass

    return action
