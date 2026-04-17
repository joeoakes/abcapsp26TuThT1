#!/usr/bin/env python3
"""
Mini Pupper maze solver simulator.
Generates a random maze (same 21x15 grid as the real game), solves it using
the AI brain (optional) or BFS fallback, streams telemetry to the dashboard,
and forwards each move to the ros_bridge on the Mini Pupper (optional).

Usage:
    python3 scripts/simulate_pupper.py                          # BFS + dashboard only
    python3 scripts/simulate_pupper.py --brain http://10.170.8.109:8001  # AI brain
    python3 scripts/simulate_pupper.py --ros-bridge http://10.170.8.209:5050  # move robot
    python3 scripts/simulate_pupper.py --brain http://10.170.8.109:8001 \\
        --ros-bridge http://10.170.8.209:5050 --url http://10.170.8.190:8080/ingest
"""

import argparse
import json
import random
import time
import uuid
from collections import deque
from datetime import datetime, timezone

try:
    import urllib.request as urlreq
    import urllib.error
except ImportError:
    import urllib.request as urlreq

MAZE_W = 21
MAZE_H = 15

# ── Maze generation (recursive backtracker, same algorithm as maze_sdl2.c) ──

def generate_maze(w, h, seed=None):
    rng = random.Random(seed)
    # Each cell: set of open walls (N S E W)
    walls = [[{"N", "S", "E", "W"} for _ in range(w)] for _ in range(h)]

    visited = [[False] * w for _ in range(h)]
    stack = [(0, 0)]
    visited[0][0] = True

    dirs = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}
    opposite = {"N": "S", "S": "N", "E": "W", "W": "E"}

    while stack:
        cx, cy = stack[-1]
        neighbors = []
        for d, (dx, dy) in dirs.items():
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx]:
                neighbors.append((d, nx, ny))
        if neighbors:
            d, nx, ny = rng.choice(neighbors)
            walls[cy][cx].discard(d)
            walls[ny][nx].discard(opposite[d])
            visited[ny][nx] = True
            stack.append((nx, ny))
        else:
            stack.pop()

    return walls


def bfs_solve(walls, w, h):
    """BFS from (0,0) to (w-1, h-1). Returns list of (x,y) positions."""
    dirs = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}
    start, goal = (0, 0), (w - 1, h - 1)
    prev = {start: None}
    q = deque([start])
    while q:
        cx, cy = q.popleft()
        if (cx, cy) == goal:
            break
        for d, (dx, dy) in dirs.items():
            nx, ny = cx + dx, cy + dy
            if (nx, ny) not in prev and d not in walls[cy][cx]:
                prev[(nx, ny)] = (cx, cy)
                q.append((nx, ny))

    path = []
    cur = goal
    while cur is not None:
        path.append(cur)
        cur = prev.get(cur)
    path.reverse()
    return path


def post(url, payload, timeout=3):
    data = json.dumps(payload).encode()
    req = urlreq.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlreq.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [warn] POST failed ({url}): {e}")
        return None


# ── AI Brain client ──────────────────────────────────────────────────────────

def walls_to_bitmask(cell_walls):
    """Convert set-of-directions to N=1,E=2,S=4,W=8 bitmask."""
    bits = 0
    if "N" in cell_walls: bits |= 1
    if "E" in cell_walls: bits |= 2
    if "S" in cell_walls: bits |= 4
    if "W" in cell_walls: bits |= 8
    return bits


def brain_init(brain_url, session_id, walls, w, h):
    cells = [{"walls": walls_to_bitmask(walls[y][x])} for y in range(h) for x in range(w)]
    payload = {
        "session_id": session_id,
        "width": w, "height": h,
        "cells": cells,
        "start_x": 0, "start_y": 0,
        "goal_x": w - 1, "goal_y": h - 1,
    }
    resp = post(f"{brain_url}/init", payload)
    return resp and resp.get("status") == "ok"


def brain_next(brain_url, session_id, x, y):
    resp = post(f"{brain_url}/next", {"session_id": session_id, "x": x, "y": y})
    if resp:
        return resp.get("action", "")
    return ""


def send_to_robot(ros_bridge_url, action, session_id, x, y):
    """Send action to robot and block until the robot finishes executing it.

    The /move endpoint on the bridge now sleeps for the action duration before
    responding, so this call naturally synchronises with the physical robot.
    Returns the duration (seconds) reported by the bridge, or 0 on failure.
    """
    if not ros_bridge_url or action in ("DONE", ""):
        return 0.0
    # Turns can take up to MAZE_TURN_DURATION (default 6 s); use a generous
    # timeout so we don't cut off the response mid-wait.
    resp = post(f"{ros_bridge_url}/move", {
        "action": action,
        "session_id": session_id,
        "x": x, "y": y,
    }, timeout=30)
    return (resp or {}).get("duration", 0.0)


def action_to_delta(action):
    return {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}.get(action, (0, 0))


def run(url, delay, seed, brain_url=None, ros_bridge_url=None):
    session_id = str(uuid.uuid4())
    robot_id = "PUPPER-01"
    print(f"Session    : {session_id}")
    print(f"Dashboard  : {url}")
    print(f"AI Brain   : {brain_url or 'BFS fallback'}")
    print(f"ROS Bridge : {ros_bridge_url or 'disabled (no robot movement)'}")
    print()

    walls = generate_maze(MAZE_W, MAZE_H, seed=seed)

    # If using AI brain, send /init
    use_brain = bool(brain_url)
    if use_brain:
        ok = brain_init(brain_url, session_id, walls, MAZE_W, MAZE_H)
        if not ok:
            print("[warn] Brain /init failed — falling back to BFS")
            use_brain = False

    if not use_brain:
        path = bfs_solve(walls, MAZE_W, MAZE_H)
        total_bfs = len(path) - 1
        print(f"BFS solved in {total_bfs} moves. Starting stream...\n")
    else:
        print(f"AI brain initialized. Starting stream (max 2000 steps)...\n")

    battery = 95.0
    battery_drain = 0.3

    x, y = 0, 0
    gx, gy = MAZE_W - 1, MAZE_H - 1
    seq = 0
    max_steps = 2000

    # BFS path iterator (only used when not using brain)
    path_iter = iter(bfs_solve(walls, MAZE_W, MAZE_H)[1:]) if not use_brain else None

    while seq < max_steps:
        goal_reached = (x == gx and y == gy)

        if goal_reached:
            print(f"\n  GOAL reached in {seq} moves!")
            if ros_bridge_url:
                send_to_robot(ros_bridge_url, "DONE", session_id, x, y)
            mission_payload = {
                "session_id": session_id,
                "event_type": "mission_complete",
                "robot_id": robot_id,
                "result": "success",
                "moves": seq,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            post(url, mission_payload)
            break

        # Get next action
        if use_brain:
            action = brain_next(brain_url, session_id, x, y)
            if not action or action == "DONE":
                print(f"\n  Brain returned {action!r} at ({x},{y}) — stopping.")
                break
            dx, dy = action_to_delta(action)
            nx, ny = x + dx, y + dy
            move_dir = {"UP": "forward", "DOWN": "reverse", "LEFT": "left", "RIGHT": "right"}.get(action, "forward")
        else:
            try:
                nx, ny = next(path_iter)
                dx, dy = nx - x, ny - y
                action = {(0,-1):"UP",(0,1):"DOWN",(-1,0):"LEFT",(1,0):"RIGHT"}.get((dx,dy),"UP")
                move_dir = {"UP":"forward","DOWN":"reverse","LEFT":"left","RIGHT":"right"}[action]
            except StopIteration:
                break

        # Forward to robot — blocks until the robot finishes the move
        if ros_bridge_url:
            send_to_robot(ros_bridge_url, action, session_id, x, y)

        x, y = nx, ny
        seq += 1
        battery = max(5.0, battery - battery_drain)

        payload = {
            "session_id": session_id,
            "event_type": "player_move",
            "robot_id": robot_id,
            "input": {
                "device": "pupper_ai" if use_brain else "pupper_sim",
                "move_sequence": seq,
                "move_dir": move_dir,
                "action": action,
            },
            "player": {"position": {"x": x, "y": y}},
            "robot": {
                "battery_pct": round(battery, 1),
                "is_charging": False,
                "battery_state": "Discharging",
            },
            "goal_reached": False,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        post(url, payload)

        pct = min(99, int(seq / max_steps * 100)) if use_brain else int(seq / max(total_bfs, 1) * 100)
        bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
        print(f"\r  [{bar}] step {seq:4d}  pos({x:2d},{y:2d})  action={action:<5}  bat {battery:.1f}%", end="", flush=True)

        # When a robot is attached the /move call already blocked for the full
        # move duration, so just add a small inter-move buffer.  Without a
        # robot, sleep the full delay so the telemetry stream isn't instant.
        if ros_bridge_url:
            time.sleep(max(0.1, delay))
        else:
            time.sleep(delay)

    print(f"\nDone. {seq} moves.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate Mini Pupper solving the maze")
    parser.add_argument("--url",        default="http://127.0.0.1:8080/ingest",  help="Dashboard ingest URL")
    parser.add_argument("--delay",      type=float, default=0.4,                 help="Seconds between moves")
    parser.add_argument("--seed",       type=int,   default=None,                help="Maze seed (random if omitted)")
    parser.add_argument("--brain",      default=None,                            help="AI brain base URL e.g. http://10.170.8.109:8001")
    parser.add_argument("--ros-bridge", default=None, dest="ros_bridge",         help="ROS bridge URL e.g. http://10.170.8.209:5050")
    args = parser.parse_args()
    run(args.url, args.delay, args.seed, brain_url=args.brain, ros_bridge_url=args.ros_bridge)
