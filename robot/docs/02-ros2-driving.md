## ROS 2: Get Mini Pupper Moving

This guide focuses on driving via `/cmd_vel` and keyboard teleop.

Note: Written for **Mini Pupper 1** in our class setup. For **Mini Pupper 2** (different model selection / packages), start from the official docs: [Mini Pupper ROS2 Guide](https://minipupperdocs.readthedocs.io/en/latest/guide/ROS2Guide.html).

---

## Verify ROS 2 Environment

On the machine where you’ll run commands (robot and/or laptop):

```bash
printenv ROS_DISTRO
```

If empty, source ROS 2 (example for Humble):

```bash
source /opt/ros/humble/setup.bash
```

---

## Bringup (Mini Pupper ROS 2 stack)

To actually move, the robot typically needs its “bringup” running (base controller, drivers, etc.). If your image uses the official Mini Pupper ROS 2 workspace layout, the flow is:

On the **robot**:

```bash
. ~/ros2_ws/install/setup.bash
ros2 launch mini_pupper_bringup bringup.launch.py
```

Then on your **laptop** (or another terminal), run teleop.

Reference: the official guide has a full end-to-end walkthrough (PC + robot setup, bringup, teleop, etc.): [Mini Pupper ROS2 Guide](https://minipupperdocs.readthedocs.io/en/latest/guide/ROS2Guide.html)

---

## Check that the robot is listening for velocity commands

On the robot (or any machine on the same ROS 2 network):

```bash
ros2 topic list
ros2 topic info /cmd_vel
```

You should see `/cmd_vel` as a topic (often `geometry_msgs/msg/Twist`).

---

## Drive by publishing to `/cmd_vel` (works everywhere)

Move forward slowly (10 Hz publish):

```bash
ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.10}, angular: {z: 0.0}}"
```

Rotate in place:

```bash
ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0}, angular: {z: 0.8}}"
```

Stop:

```bash
ros2 topic pub -1 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0}, angular: {z: 0.0}}"
```

---

## Keyboard Teleop (Recommended)

If you have `teleop_twist_keyboard` installed:

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel
```

Keyboard controls (common defaults):

- **Stop**: `k`
- **Forward / backward**: `i` / `,`
- **Turn left / right (in place)**: `j` / `l`
- **Forward-left / forward-right**: `u` / `o`
- **Backward-left / backward-right**: `m` / `.`
- **Speed scaling**: `q` / `z` increase/decrease all speeds, `w` / `x` increase/decrease linear only, `e` / `c` increase/decrease angular only

Tip: keep one finger near `k` so you can stop immediately.

If it’s missing, install on Ubuntu:

```bash
sudo apt update
sudo apt install -y ros-humble-teleop-twist-keyboard
```

---

## ROS 2 Networking Note (laptop <-> robot)

If you run ROS 2 commands from your laptop and they don’t “see” the robot:

- Ensure both are on the **same Wi‑Fi**.
- Ensure both use the same **ROS domain**:

```bash
echo $ROS_DOMAIN_ID
export ROS_DOMAIN_ID=0
```

If you choose a non-default value, it must match on **both** the robot and your laptop (the official guide uses an example like `42`).

- If your course uses a specific middleware, you may need:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```
