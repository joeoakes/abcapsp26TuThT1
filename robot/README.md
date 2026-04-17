# Mini Pupper 1 (Robot) Docs

These docs explain how to connect to **Mini Pupper 1**, drive it with **ROS 2**, and set up/test the **camera**.

We primarily use **Ubuntu Linux**, but the connection/IP/SSH steps include **macOS** and **Windows** options too.

If you have **Mini Pupper 2**, do **not** assume the same hardware layout, usernames, or ROS 2 bringup packages. Use the official docs as your starting point:

- [Mini Pupper ROS2 Guide](https://minipupperdocs.readthedocs.io/en/latest/guide/ROS2Guide.html)
- [Mini Pupper assembly/cover notes](https://minipupperdocs.readthedocs.io/en/latest/guide/Assembly/MiniPupper.html#cover-assembly)

---

## What you’re looking for

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
