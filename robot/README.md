# Mini Pupper 1 (Robot) Docs

These docs explain how to connect to **Mini Pupper 1**, drive it with **ROS 2**, and set up/test the **camera**.

We primarily use **Ubuntu Linux**, but the connection/IP/SSH steps include **macOS** and **Windows** options too.

If you have **Mini Pupper 2**, do **not** assume the same hardware layout, usernames, or ROS 2 bringup packages. Use the official docs as your starting point:

- [Mini Pupper ROS2 Guide](https://minipupperdocs.readthedocs.io/en/latest/guide/ROS2Guide.html)
- [Mini Pupper assembly/cover notes](https://minipupperdocs.readthedocs.io/en/latest/guide/Assembly/MiniPupper.html#cover-assembly)

---

## What you're looking for

- **Connect + find IP + SSH**: `docs/01-connect-ssh-ip.md`
  - Power ports (USB‑C vs micro‑USB), microSD notes, safe SD removal, find IP, SSH (`minipupper1@...`), password, DHCP reservation
- **Driving with ROS 2**: `docs/02-ros2-driving.md`
  - `/cmd_vel`, `teleop_twist_keyboard` + key map, ROS 2 networking notes
- **Camera setup + testing**: `docs/03-camera.md`
  - venv (NumPy/OpenCV), raw frame → PNG → `scp`, frame stats validation, ROS 2 camera viewing
- **Troubleshooting**: `docs/04-troubleshooting.md`
  - recommended system update + quick common fixes

---

## AI Brain -> Mini Pupper quickstart

If you want Mini Pupper to follow `maze_brain` decisions directly:

1) On the AI-brain host, start maze_brain with robot forwarding:

```bash
cd /path/to/abcapsp26TuThT1
bash scripts/start_maze_brain_forward_robot.sh
```

You can override the robot bridge endpoint:

```bash
ROBOT_BRIDGE_URL="http://10.170.8.209:5050" bash scripts/start_maze_brain_forward_robot.sh
```

1) On Mini Pupper, start the listener stack (bridge + ROS2 command node):

```bash
cd ~/abcapsp26TuThT1
bash robot/start_minipupper_listener.sh
```

1) Tune motion to match virtual maze cell-by-cell behavior:

```bash
MAZE_TURN_90_DURATION=0.85 MAZE_CELL_MOVE_DURATION=0.60 bash robot/start_minipupper_listener.sh
```

1) Stop listeners:

```bash
bash robot/stop_minipupper_listener.sh
```

---


## Manual Control Guide (Team 1TT maze pipeline)

How to start the robot and send move commands from your own terminal.

### Prerequisites

- Connected to the lab VPN
- `sshpass` installed (`brew install sshpass` on Mac)
- `.env` loaded in your terminal (`source .env` from repo root)

---

### Step 1 — Start the ROS2 bringup on the Pupper

SSH into the Pupper and run bringup. Leave this terminal open — it must keep running.

```bash
ssh ubuntu@10.170.8.209          # password: mangdang
ros2 launch mini_pupper_bringup bringup.launch.py
```

---

### Step 2 — Start the HTTP bridge (ros_bridge)

Open a **new** SSH terminal on the Pupper:

```bash
ssh ubuntu@10.170.8.209
cd ~/abcapsp26TuThT1/robot
REDIS_HOST=127.0.0.1 REDIS_PORT=6379 \
MAZE_STEP_DURATION=0.6 MAZE_TURN_DURATION=6.0 \
python3 -m uvicorn ros_bridge:app --host 0.0.0.0 --port 5050
```

Verify it's up:
```bash
curl http://10.170.8.209:5050/health
# Expected: {"ok":true}
```

---

### Step 3 — Start the ROS bridge node (ros_bridge_node)

Open another **new** SSH terminal on the Pupper:

```bash
ssh ubuntu@10.170.8.209
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
cd ~/abcapsp26TuThT1/robot

ROS_DOMAIN_ID=42 \
REDIS_HOST=127.0.0.1 \
REDIS_PORT=6379 \
MAZE_STEP_LINEAR=0.15 \
MAZE_STEP_ANGULAR=0.8 \
MAZE_CELL_MOVE_DURATION=0.50 \
MAZE_TURN_90_DURATION=6.0 \
python3 ros_bridge_node.py
```

You should see:
```
[INFO] [maze_ros_bridge]: Maze ROS Bridge started
```

---

### Step 4 — Send move commands from your laptop

```bash
# Forward
curl -X POST http://10.170.8.209:5050/move \
  -H "Content-Type: application/json" \
  -d '{"action":"UP","session_id":"test","x":0,"y":0}'

# Backward
curl -X POST http://10.170.8.209:5050/move \
  -H "Content-Type: application/json" \
  -d '{"action":"DOWN","session_id":"test","x":0,"y":0}'

# Turn left (90°)
curl -X POST http://10.170.8.209:5050/move \
  -H "Content-Type: application/json" \
  -d '{"action":"LEFT","session_id":"test","x":0,"y":0}'

# Turn right (90°)
curl -X POST http://10.170.8.209:5050/move \
  -H "Content-Type: application/json" \
  -d '{"action":"RIGHT","session_id":"test","x":0,"y":0}'
```

> UP/DOWN return after ~0.6s. LEFT/RIGHT block for ~6s while the robot completes the full 90° turn.

---

### How it works

```
Your laptop
  └─ POST /move → ros_bridge.py (port 5050)
       └─ Redis pubsub "maze_actions"
            └─ ros_bridge_node.py
                 └─ /cmd_vel (geometry_msgs/Twist)
                      └─ quadruped_controller (CHAMP, ROS_DOMAIN_ID=42)
                           └─ servo_interface → legs move
```

---

### Timing reference

| Action | linear.x | angular.z | Duration |
|--------|----------|-----------|----------|
| UP     | -0.15    | 0.0       | 0.50s    |
| DOWN   | +0.15    | 0.0       | 0.50s    |
| LEFT   | 0.0      | +0.8      | 6.0s     |
| RIGHT  | 0.0      | -0.8      | 6.0s     |

---

### Troubleshooting

**Robot doesn't move:**
- Confirm bringup is still running: `ps aux | grep bringup`
- Check the node is subscribed: `redis-cli pubsub numsub maze_actions` → should be `1`
- Kill duplicate nodes: `ps aux | grep ros_bridge_node | grep -v grep` — there should be exactly one

**ROS_DOMAIN_ID mismatch (commands ignored silently):**
- Bringup and ros_bridge_node must both use domain 42
- Check: `cat /proc/$(pgrep -f bringup | head -1)/environ | tr '\0' '\n' | grep ROS_DOMAIN`

**Commands pile up / robot won't stop:**
- Send a stop: `curl -X POST http://10.170.8.209:5050/move -H "Content-Type: application/json" -d '{"action":"DONE","session_id":"t","x":0,"y":0}'`
