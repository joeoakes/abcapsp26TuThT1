#!/usr/bin/env python3
"""
Mini Pupper maze solver simulator.
Generates a random maze (same 21x15 grid as the real game), solves it with BFS,
then streams telemetry to the dashboard as if the pupper is walking it live.

Usage:
    python3 scripts/simulate_pupper.py [--url http://127.0.0.1:8080/ingest] [--delay 0.4]
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


def post(url, payload):
    data = json.dumps(payload).encode()
    req = urlreq.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlreq.urlopen(req, timeout=5) as r:
            return r.status
    except Exception as e:
        print(f"  [warn] POST failed: {e}")
        return None


def run(url, delay, seed):
    session_id = str(uuid.uuid4())
    robot_id = "PUPPER-01"
    print(f"Session : {session_id}")
    print(f"Endpoint: {url}")
    print(f"Delay   : {delay}s per move\n")

    walls = generate_maze(MAZE_W, MAZE_H, seed=seed)
    path  = bfs_solve(walls, MAZE_W, MAZE_H)
    total = len(path) - 1  # number of moves

    print(f"Maze solved in {total} moves. Starting stream...\n")

    battery = 95.0
    battery_drain = 0.3  # per move

    for seq, (x, y) in enumerate(path):
        goal_reached = (x == MAZE_W - 1 and y == MAZE_H - 1)

        # Infer direction from previous position
        move_dir = "forward"
        if seq > 0:
            px, py = path[seq - 1]
            dx, dy = x - px, y - py
            if   dx ==  1: move_dir = "right"
            elif dx == -1: move_dir = "left"
            elif dy == -1: move_dir = "forward"
            elif dy ==  1: move_dir = "reverse"

        battery = max(5.0, battery - battery_drain)

        payload = {
            "session_id": session_id,
            "event_type": "player_move",
            "robot_id": robot_id,
            "input": {
                "device": "pupper_sim",
                "move_sequence": seq,
                "move_dir": move_dir,
            },
            "player": {
                "position": {"x": x, "y": y},
            },
            "robot": {
                "battery_pct": round(battery, 1),
                "is_charging": False,
                "battery_state": "Discharging",
            },
            "goal_reached": goal_reached,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        status = post(url, payload)
        pct = int(seq / max(total, 1) * 100)
        bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
        print(f"\r  [{bar}] {pct:3d}%  move {seq:4d}/{total}  pos({x:2d},{y:2d})  bat {battery:.1f}%  {'GOAL!' if goal_reached else '     '}", end="", flush=True)

        if goal_reached:
            print()
            # Send mission summary
            mission_payload = {
                "session_id": session_id,
                "event_type": "mission_complete",
                "robot_id": robot_id,
                "result": "success",
                "moves": total,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            post(url, mission_payload)
            break

        time.sleep(delay)

    print(f"\nDone. {total} moves streamed to dashboard.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate Mini Pupper solving the maze")
    parser.add_argument("--url",   default="http://127.0.0.1:8080/ingest", help="Dashboard ingest URL")
    parser.add_argument("--delay", type=float, default=0.4,               help="Seconds between moves")
    parser.add_argument("--seed",  type=int,   default=None,              help="Maze seed (random if omitted)")
    args = parser.parse_args()
    run(args.url, args.delay, args.seed)
