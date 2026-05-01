"""
ROS 2 node that listens on a Redis channel for maze actions and publishes
geometry_msgs/Twist to /cmd_vel.
"""

import os
import time
import json

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import redis

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


LINEAR_SPEED = float(os.getenv("MAZE_STEP_LINEAR", "0.15"))       # m/s
ANGULAR_SPEED = float(os.getenv("MAZE_STEP_ANGULAR", "0.8"))      # rad/s
STEP_DURATION = float(os.getenv("MAZE_STEP_DURATION", "0.6"))     # seconds for UP/DOWN
TURN_DURATION = float(os.getenv("MAZE_TURN_DURATION", "6.0"))     # seconds for LEFT/RIGHT (1 cmd = 90°)
TURN_90_DURATION = float(os.getenv("MAZE_TURN_90_DURATION", "0.85"))
CELL_MOVE_DURATION = float(os.getenv("MAZE_CELL_MOVE_DURATION", "0.60"))
REVERSE_CELL_MOVE_DURATION = float(os.getenv("MAZE_REVERSE_CELL_MOVE_DURATION", str(CELL_MOVE_DURATION)))
ACTION_MODE = os.getenv("MAZE_ACTION_MODE", "grid_absolute").strip().lower()
CMD_HZ = float(os.getenv("MAZE_CMD_HZ", "10.0"))
FORWARD_SIGN = float(os.getenv("MAZE_FORWARD_SIGN", "1.0"))
REVERSE_ON_OPPOSITE = env_bool("MAZE_REVERSE_ON_OPPOSITE", "1")
INITIAL_HEADING = int(os.getenv("MAZE_INITIAL_HEADING", "0")) % 4
SWAP_UP_DOWN = env_bool("MAZE_SWAP_UP_DOWN", "0")
TOPIC = os.getenv("MAZE_CMD_VEL_TOPIC", "/cmd_vel")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL = "maze_actions"
RESULT_CHANNEL = "maze_action_results"

# Simple mode action map. FORWARD_SIGN captures which linear.x sign is
# physical forward for this robot/controller setup.
simple_forward = FORWARD_SIGN * abs(LINEAR_SPEED)
simple_backward = -simple_forward
up_linear = simple_backward if SWAP_UP_DOWN else simple_forward
down_linear = simple_forward if SWAP_UP_DOWN else simple_backward
ACTION_MAP = {
    "UP": (up_linear, 0.0),
    "DOWN": (down_linear, 0.0),
    "RIGHT": (0.0, -ANGULAR_SPEED),  # clockwise
    "LEFT": (0.0, ANGULAR_SPEED),
}

# Absolute maze action to heading index: 0=N(UP),1=E(RIGHT),2=S(DOWN),3=W(LEFT)
HEADING_TARGET = {
    "UP": 0,
    "RIGHT": 1,
    "DOWN": 2,
    "LEFT": 3,
}
if SWAP_UP_DOWN:
    HEADING_TARGET["UP"], HEADING_TARGET["DOWN"] = (
        HEADING_TARGET["DOWN"],
        HEADING_TARGET["UP"],
    )


class MazeBridgeNode(Node):
    def __init__(self):
        super().__init__("maze_ros_bridge")
        self.pub = self.create_publisher(Twist, TOPIC, 10)
        self.heading = INITIAL_HEADING
        self.get_logger().info(f"Publishing to {TOPIC}")
        self.get_logger().info(
            f"ACTION_MODE={ACTION_MODE} LINEAR={LINEAR_SPEED} ANGULAR={ANGULAR_SPEED}"
        )
        self.get_logger().info(
            f"STEP_DURATION={STEP_DURATION}s TURN_DURATION={TURN_DURATION}s "
            f"TURN_90_DURATION={TURN_90_DURATION}s CELL_MOVE_DURATION={CELL_MOVE_DURATION}s "
            f"REVERSE_CELL_MOVE_DURATION={REVERSE_CELL_MOVE_DURATION}s"
        )
        self.get_logger().info(
            f"CMD_HZ={CMD_HZ} FORWARD_SIGN={FORWARD_SIGN} "
            f"REVERSE_ON_OPPOSITE={REVERSE_ON_OPPOSITE} INITIAL_HEADING={INITIAL_HEADING} "
            f"SWAP_UP_DOWN={SWAP_UP_DOWN}"
        )

    def publish_for_duration(self, linear_x: float, angular_z: float, duration_s: float) -> None:
        msg = Twist()
        msg.linear.x = linear_x
        msg.angular.z = angular_z
        duration_s = max(0.0, duration_s)
        period_s = 1.0 / max(0.1, CMD_HZ)
        deadline = time.monotonic() + duration_s

        while time.monotonic() < deadline:
            self.pub.publish(msg)
            remaining = deadline - time.monotonic()
            time.sleep(min(period_s, max(0.0, remaining)))

        self.pub.publish(Twist())

    def rotate_quarters(self, quarter_turns: int) -> None:
        # +1 = left 90, -1 = right 90, +/-2 = 180
        while quarter_turns != 0:
            step = 1 if quarter_turns > 0 else -1
            az = ANGULAR_SPEED if step > 0 else -ANGULAR_SPEED
            self.publish_for_duration(0.0, az, TURN_90_DURATION)
            self.heading = (self.heading + step) % 4
            quarter_turns -= step

    def execute_grid_absolute_action(self, action: str) -> bool:
        if action not in HEADING_TARGET:
            self.get_logger().warn(f"Unknown action: {action!r} — ignored")
            return False

        target = HEADING_TARGET[action]
        diff = (target - self.heading) % 4
        if diff == 2 and REVERSE_ON_OPPOSITE:
            backward_speed = -(FORWARD_SIGN * abs(LINEAR_SPEED))
            self.get_logger().info(
                f"Grid action={action} heading={self.heading} target={target} "
                "opposite=true reverse_one_cell=true"
            )
            self.publish_for_duration(backward_speed, 0.0, REVERSE_CELL_MOVE_DURATION)
            return True

        if diff == 3:
            quarter_turns = -1
        elif diff == 2:
            quarter_turns = 2
        else:
            quarter_turns = diff

        self.get_logger().info(
            f"Grid action={action} heading={self.heading} target={target} rotate_q={quarter_turns}"
        )
        if quarter_turns != 0:
            self.rotate_quarters(quarter_turns)
        else:
            self.get_logger().info("Same absolute direction as current heading; walking forward only")

        forward_speed = FORWARD_SIGN * abs(LINEAR_SPEED)
        self.publish_for_duration(forward_speed, 0.0, CELL_MOVE_DURATION)
        return True

    def execute_action(self, action: str) -> tuple[bool, float]:
        started_at = time.monotonic()
        action = action.strip().upper()
        if action == "DONE":
            self.get_logger().info("DONE received, publishing stop.")
            self.pub.publish(Twist())
            return True, time.monotonic() - started_at

        if ACTION_MODE == "grid_absolute":
            ok = self.execute_grid_absolute_action(action)
            return ok, time.monotonic() - started_at

        if action not in ACTION_MAP:
            self.get_logger().warn(f"Unknown action: {action!r} — ignored")
            return False, time.monotonic() - started_at

        lx, az = ACTION_MAP[action]
        # Use TURN_DURATION for left/right so one command = one 90-degree turn
        duration = TURN_DURATION if action in ("LEFT", "RIGHT") else STEP_DURATION
        self.get_logger().info(
            f"Action={action} linear.x={lx} angular.z={az} dur={duration}s"
        )
        self.publish_for_duration(lx, az, duration)
        return True, time.monotonic() - started_at


def main():
    rclpy.init()
    node = MazeBridgeNode()

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    pubsub = r.pubsub()
    pubsub.subscribe(REDIS_CHANNEL)

    node.get_logger().info(
        f"Subscribed to Redis channel '{REDIS_CHANNEL}' on {REDIS_HOST}:{REDIS_PORT}"
    )
    node.get_logger().info("Waiting for maze actions...")

    try:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                payload = json.loads(message["data"])
                action = payload.get("action", "")
                command_id = payload.get("command_id", "")
            except (json.JSONDecodeError, AttributeError):
                action = str(message["data"])
                command_id = ""

            try:
                ok, duration = node.execute_action(action)
                status = "ok" if ok else "ignored"
            except Exception as exc:
                node.get_logger().error(f"Command execution failed: {exc}")
                node.pub.publish(Twist())
                ok = False
                duration = 0.0
                status = "error"

            if command_id:
                result = {
                    "command_id": command_id,
                    "action": action,
                    "status": status,
                    "duration": duration,
                }
                r.publish(RESULT_CHANNEL, json.dumps(result))
            rclpy.spin_once(node, timeout_sec=0.0)

    except KeyboardInterrupt:
        pass
    finally:
        pubsub.unsubscribe()
        node.pub.publish(Twist())  # safety stop on exit
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
