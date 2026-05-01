# Telemetry

This folder contains the telemetry JSON schema used across the maze project.

## Schema

See `telemetry.json` for a complete example. The fields are:

- **team** — Team identifier (e.g. `"team1tt"`)
- **event_type** — Type of event (e.g. `"player_move"`)
- **input.device** — Input device (`"keyboard"`, `"joystick"`)
- **input.move_sequence** — Sequential move counter
- **player.position.x / y** — Player coordinates in the maze grid
- **goal_reached** — `true` if the player reached the goal on this move
- **timestamp** — ISO-8601 UTC timestamp
- **session_id** — UUID identifying the play session
- **move_dir** — Movement direction for Mini-Pupper (`"forward"`, `"backward"`, `"left"`, `"right"`, `"stop"`)

Note: `move_dir` is legacy/body-relative telemetry. The supported AI maze robot path uses `action` values (`UP`, `DOWN`, `LEFT`, `RIGHT`, `DONE`) through `robot/ros_bridge.py` and `robot/ros_bridge_node.py`, where each action maps to an absolute maze-grid cell movement.

## Usage

### Maze SDL2 client → HTTPS servers

The `maze_sdl2` app sends telemetry on every move to:
- **Logging server** (`maze_https_mongo`) — stores in MongoDB
- **AI server** (`maze_https_redis`) — stores in Redis
- **Mini-Pupper server** (`maze_https_minipupper`) — legacy/manual server that translates body-relative `move_dir` to ROS2 `/cmd_vel`

### curl example

```bash
curl -k -X POST https://localhost:8443/move \
     -H "Content-Type: application/json" \
     -d @telemetry.json
```
