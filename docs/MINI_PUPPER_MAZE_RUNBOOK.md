# Mini Pupper AI Maze Runbook

This is the supported run path for the physical Mini Pupper maze demo:

```text
local maze/maze_sdl2
  -> AI server A* brain on :8010
  -> Mini Pupper HTTP bridge on :5050
  -> Redis maze_actions / maze_action_results
  -> ROS 2 /cmd_vel
  -> Mini Pupper gait controller
```

Do not use `https/maze_https_minipupper.c` for AI autoplay. That C server is a legacy/manual body-relative controller. The supported AI maze path is the Python bridge in `robot/`.

## Current Tuned Behavior

The robot bridge runs in `grid_absolute` mode.

| Maze action | Physical behavior |
| --- | --- |
| `DOWN` | Move forward from the robot wake-up heading |
| `UP` | Move in the opposite maze direction |
| `RIGHT` | Rotate to the absolute right/east heading, then move one cell |
| `LEFT` | Rotate to the absolute left/west heading, then move one cell |
| repeated same direction | Walk forward only, no extra turn |
| opposite direction | Reverse one cell when `MAZE_REVERSE_ON_OPPOSITE=1` |
| `DONE` | Publish zero velocity and stop |

The current physical tuning is for a Mini Pupper on thin carpet with a lightweight AprilTag cube mounted near the front:

```bash
MAZE_ACTION_MODE=grid_absolute
MAZE_STEP_LINEAR=0.13
MAZE_STEP_ANGULAR=0.8
MAZE_TURN_90_DURATION=2.05
MAZE_CELL_MOVE_DURATION=1.40
MAZE_REVERSE_CELL_MOVE_DURATION=1.40
MAZE_CMD_HZ=15
MAZE_FORWARD_SIGN=1.0
MAZE_REVERSE_ON_OPPOSITE=1
MAZE_INITIAL_HEADING=0
MAZE_SWAP_UP_DOWN=1
```

`MAZE_FORWARD_SIGN=1.0` is important. If the robot walks backward when the maze ticker goes down, this is the first setting to check.

## Hosts

| Role | Host |
| --- | --- |
| Mini Pupper | `ubuntu@10.170.8.209` |
| AI server | `mta5343@10.170.8.109` |
| AI brain port | `8010` |
| Mini Pupper bridge port | `5050` |

Connect to the VPN before running these commands.

## One-Time Prep

Build the local maze app from the repository root:

```bash
bash scripts/build.sh
```

Make sure the AI server has the Python environment used by `maze_brain`:

```bash
ssh mta5343@10.170.8.109
cd /home/mta5343/abcapsp26TuThT1
source .venv/bin/activate
python -m pip install -r robot/requirements.txt
```

Make sure the Mini Pupper has this repo at:

```text
/home/ubuntu/abcapsp26TuThT1
```

## Cold Start Procedure

Run these steps from your laptop.

### 1. Stop Any Old Local Maze App

```bash
screen -S maze_app -X quit 2>/dev/null || true
pkill -f '/maze_sdl2|maze/maze_sdl2|\.\/maze_sdl2' 2>/dev/null || true
rm -f /tmp/maze_app.log
```

### 2. Stop Any Existing Robot Motion

This is safe to run even if the bridge is not up:

```bash
curl -sS --max-time 10 \
  -X POST http://10.170.8.209:5050/move \
  -H 'Content-Type: application/json' \
  -d '{"action":"DONE","session_id":"operator-stop","x":0,"y":0}' || true
```

### 3. Reboot the Mini Pupper

```bash
ssh ubuntu@10.170.8.209 'sudo reboot'
```

Wait for SSH to return:

```bash
until nc -z -w 2 10.170.8.209 22; do
  sleep 2
done
echo "Mini Pupper SSH is back"
```

### 4. Update and Start the Mini Pupper Stack

```bash
ssh ubuntu@10.170.8.209 'bash -lc "
  cd /home/ubuntu/abcapsp26TuThT1 &&
  git pull --ff-only &&
  bash robot/start_minipupper_stack.sh
"'
```

Expected status includes:

```text
{"ok":true}
maze_actions
1
ACTION_MODE=grid_absolute LINEAR=0.13 ANGULAR=0.8
CMD_HZ=15.0 FORWARD_SIGN=1.0 ... SWAP_UP_DOWN=True
```

If bringup prints a lidar startup error but the bridge is healthy and `maze_actions` has one subscriber, the maze velocity path can still run.

### 5. Verify Robot Bridge Health

```bash
curl -sS --max-time 8 http://10.170.8.209:5050/health
```

Expected:

```json
{"ok":true}
```

Run one non-moving stop ack check:

```bash
curl -sS --max-time 20 \
  -X POST http://10.170.8.209:5050/move \
  -H 'Content-Type: application/json' \
  -d '{"action":"DONE","session_id":"ready-check","x":0,"y":0}'
```

Expected response has `status:"ok"` and a `command_id`.

### 6. Start the A* Brain on the AI Server

```bash
ssh mta5343@10.170.8.109 'bash -s' <<'SCRIPT'
set -euo pipefail
cd /home/mta5343/abcapsp26TuThT1

if ! redis-cli ping >/dev/null 2>&1; then
  redis-server --daemonize yes
  sleep 1
fi

tmux kill-session -t maze_astar 2>/dev/null || true
pkill -f 'python -m uvicorn maze_brain:app' 2>/dev/null || true
rm -f /tmp/maze_astar.log /tmp/maze_astar.pid

nohup bash -lc '
  cd /home/mta5343/abcapsp26TuThT1 &&
  source .venv/bin/activate &&
  PYTHONPATH=/home/mta5343/abcapsp26TuThT1/maze_brain \
  REDIS_HOST=127.0.0.1 \
  REDIS_PORT=6379 \
  ROBOT_BRIDGE_URL=http://10.170.8.209:5050 \
  ROBOT_BRIDGE_TIMEOUT_S=60 \
  ROBOT_BRIDGE_REQUIRED=1 \
  python -m uvicorn maze_brain:app --host 0.0.0.0 --port 8010
' >/tmp/maze_astar.log 2>&1 &

printf '%s\n' "$!" > /tmp/maze_astar.pid

for _ in $(seq 1 25); do
  if curl -fsS http://127.0.0.1:8010/health >/dev/null 2>&1; then
    curl -s http://127.0.0.1:8010/health
    printf '\npid='
    cat /tmp/maze_astar.pid
    exit 0
  fi
  sleep 1
done

tail -80 /tmp/maze_astar.log || true
exit 1
SCRIPT
```

### 7. Start the Local Maze App

```bash
screen -S maze_app -X quit 2>/dev/null || true
pkill -f '/maze_sdl2|maze/maze_sdl2|\.\/maze_sdl2' 2>/dev/null || true
rm -f /tmp/maze_app.log

curl -fsS --max-time 5 http://10.170.8.109:8010/health >/dev/null

screen -dmS maze_app bash -lc '
  cd /Users/mostafa/abcapsp26TuThT1/maze &&
  MAZE_AUTOPLAY=1 \
  MAZE_BRAIN_INIT_URL=http://10.170.8.109:8010/init \
  MAZE_BRAIN_NEXT_URL=http://10.170.8.109:8010/next \
  ./maze_sdl2 > /tmp/maze_app.log 2>&1
'
```

Check that it is running:

```bash
screen -ls
pgrep -af 'maze_sdl2|maze_app' || true
tail -80 /tmp/maze_app.log 2>/dev/null || true
```

The local maze log should usually be empty while the app is running normally.

## Live Monitoring

AI server:

```bash
ssh mta5343@10.170.8.109 'tail -120 /tmp/maze_astar.log'
```

Mini Pupper bridge and ROS listener:

```bash
ssh ubuntu@10.170.8.209 'tail -100 /tmp/ros_bridge.log; tail -100 /tmp/ros_bridge_node.log'
```

Local maze app:

```bash
screen -ls
tail -120 /tmp/maze_app.log
```

Useful healthy signs:

- AI log says `Forwarded action=... to robot bridge`.
- Robot bridge log says `Move complete: command_id=...`.
- ROS node log says `Grid action=DOWN heading=0 target=0 rotate_q=0` for forward-from-start moves.
- Repeated same-direction moves log `Same absolute direction as current heading; walking forward only`.

## Manual Movement Test

Use this before a full maze run if you need to confirm direction:

```bash
curl -sS --max-time 25 \
  -X POST http://10.170.8.209:5050/move \
  -H 'Content-Type: application/json' \
  -d '{"action":"DOWN","session_id":"manual-down-forward-test","x":0,"y":0}'

curl -sS --max-time 10 \
  -X POST http://10.170.8.209:5050/move \
  -H 'Content-Type: application/json' \
  -d '{"action":"DONE","session_id":"manual-stop","x":0,"y":0}'
```

With the current calibration, `DOWN` should move the robot physically forward from its wake-up heading.

## Stop Procedure

Stop the maze app:

```bash
screen -S maze_app -X quit 2>/dev/null || true
pkill -f '/maze_sdl2|maze/maze_sdl2|\.\/maze_sdl2' 2>/dev/null || true
```

Stop robot motion:

```bash
curl -sS --max-time 10 \
  -X POST http://10.170.8.209:5050/move \
  -H 'Content-Type: application/json' \
  -d '{"action":"DONE","session_id":"operator-stop","x":0,"y":0}' || true
```

Stop the Mini Pupper stack:

```bash
ssh ubuntu@10.170.8.209 'cd /home/ubuntu/abcapsp26TuThT1 && bash robot/stop_minipupper_listener.sh'
```

Stop the AI brain:

```bash
ssh mta5343@10.170.8.109 'pkill -f "python -m uvicorn maze_brain:app" 2>/dev/null || true'
```

## Tuning Guide

Change these only one at a time:

- Robot moves backward when ticker goes `DOWN`: flip `MAZE_FORWARD_SIGN`.
- Robot struggles to move forward: reduce `MAZE_STEP_LINEAR` and increase `MAZE_CELL_MOVE_DURATION`.
- Robot under-travels one cell: increase `MAZE_CELL_MOVE_DURATION`.
- Robot over-travels one cell: decrease `MAZE_CELL_MOVE_DURATION`.
- Robot under-turns 90 degrees: increase `MAZE_TURN_90_DURATION`.
- Robot over-turns 90 degrees: decrease `MAZE_TURN_90_DURATION`.
- Maze `UP`/`DOWN` are reversed relative to the physical setup: change `MAZE_SWAP_UP_DOWN`.

For the current front-mounted AprilTag cube, prefer slower/longer forward motion over higher speed. The cube shifts weight toward the front, so aggressive forward velocity can make the robot hang or stall.

## Troubleshooting

### `/move` returns HTTP 504

The HTTP bridge published a command but did not receive the matching Redis completion ack.

Check the Mini Pupper:

```bash
ssh ubuntu@10.170.8.209 'redis-cli pubsub numsub maze_actions; tail -80 /tmp/ros_bridge_node.log'
```

Expected subscriber count is `1`.

### Maze app closes

The local log may show:

```text
mission_result":"aborted","abort_reason":"window closed"
```

Send `DONE` immediately, then relaunch the maze app.

### AI server SSH session times out

The A* brain is started with `nohup`, so reconnect and inspect:

```bash
ssh mta5343@10.170.8.109 'cat /tmp/maze_astar.pid; tail -80 /tmp/maze_astar.log'
```

### Mini Pupper does not return after reboot

Check VPN, robot power, and Wi-Fi. Do not start the AI brain or maze app until:

```bash
nc -z -w 2 10.170.8.209 22
```

returns success.
