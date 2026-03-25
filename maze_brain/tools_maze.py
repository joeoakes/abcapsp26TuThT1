# tools_maze.py
import math
import heapq
from typing import Dict, List, Tuple, Optional

# Wall bitmask: 1=N, 2=E, 4=S, 8=W
WALL_N, WALL_E, WALL_S, WALL_W = 1, 2, 4, 8

DIRECTIONS: Dict[str, Tuple[int, int, int]] = {
    "UP":    (0, -1, WALL_N),
    "RIGHT": (1,  0, WALL_E),
    "DOWN":  (0,  1, WALL_S),
    "LEFT":  (-1, 0, WALL_W),
}

def idx(width: int, x: int, y: int) -> int:
    return y * width + x

def in_bounds(width: int, height: int, x: int, y: int) -> bool:
    return 0 <= x < width and 0 <= y < height

def legal_moves(width: int, height: int, cells: List[Dict[str, int]], x: int, y: int) -> List[str]:
    moves = []
    w = cells[idx(width, x, y)]["walls"]
    for m, (dx, dy, wall_bit) in DIRECTIONS.items():
        nx, ny = x + dx, y + dy
        if in_bounds(width, height, nx, ny) and not (w & wall_bit):
            moves.append(m)
    return moves

def apply_move(x: int, y: int, move: str) -> Tuple[int, int]:
    dx, dy, _ = DIRECTIONS[move]
    return x + dx, y + dy

def validate_plan(plan: List[str], width: int, height: int, cells: List[Dict[str, int]],
                  start_x: int, start_y: int) -> bool:
    x, y = start_x, start_y
    for m in plan:
        if m not in DIRECTIONS:
            return False
        w = cells[idx(width, x, y)]["walls"]
        dx, dy, wall_bit = DIRECTIONS[m]
        if w & wall_bit:
            return False
        x, y = x + dx, y + dy
        if not in_bounds(width, height, x, y):
            return False
    return True

def analyze_maze(width: int, height: int, cells: List[Dict[str, int]]) -> Dict[str, float]:
    dead_ends = 0
    total_openings = 0
    for y in range(height):
        for x in range(width):
            w = cells[idx(width, x, y)]["walls"]
            open_sides = 0
            if not (w & WALL_N): open_sides += 1
            if not (w & WALL_E): open_sides += 1
            if not (w & WALL_S): open_sides += 1
            if not (w & WALL_W): open_sides += 1
            total_openings += open_sides
            if open_sides == 1:
                dead_ends += 1

    avg_branch = total_openings / (width * height)
    return {
        "dead_ends": float(dead_ends),
        "avg_branching_factor": round(avg_branch, 2),
        "complexity_score": round(dead_ends + avg_branch, 2),
    }

def manhattan(a: Tuple[int,int], b: Tuple[int,int]) -> int:
    return abs(a[0]-b[0]) + abs(a[1]-b[1])

def astar(width: int, height: int, cells: List[Dict[str, int]],
          start: Tuple[int,int], goal: Tuple[int,int]) -> List[str]:
    sx, sy = start
    gx, gy = goal

    pq = []
    heapq.heappush(pq, (0 + manhattan(start, goal), 0, sx, sy))
    came_from: Dict[Tuple[int,int], Tuple[Tuple[int,int], str]] = {}
    gscore = { (sx,sy): 0 }

    while pq:
        _, cost, x, y = heapq.heappop(pq)
        if (x,y) == (gx,gy):
            # reconstruct
            path = []
            cur = (x,y)
            while cur != (sx,sy):
                prev, move = came_from[cur]
                path.append(move)
                cur = prev
            path.reverse()
            return path

        for m in legal_moves(width, height, cells, x, y):
            nx, ny = apply_move(x, y, m)
            ncost = cost + 1
            if (nx,ny) not in gscore or ncost < gscore[(nx,ny)]:
                gscore[(nx,ny)] = ncost
                came_from[(nx,ny)] = ((x,y), m)
                pr = ncost + manhattan((nx,ny), (gx,gy))
                heapq.heappush(pq, (pr, ncost, nx, ny))

    return []

def score_plan(plan: List[str], optimal: List[str]) -> Dict[str, object]:
    if not plan:
        return {"valid": False}
    return {
        "valid": True,
        "length": len(plan),
        "optimal_length": len(optimal),
        "is_optimal": len(plan) == len(optimal),
        "overhead": len(plan) - len(optimal),
    }
