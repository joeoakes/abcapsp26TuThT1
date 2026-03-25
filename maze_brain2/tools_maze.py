from typing import Dict, List, Tuple

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

def score_plan(plan: List[str], goal_reached: bool) -> Dict[str, object]:
    return {
        "valid": bool(plan),
        "length": len(plan),
        "goal_reached": bool(goal_reached),
    }
