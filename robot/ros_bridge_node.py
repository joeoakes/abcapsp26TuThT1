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
LINEAR_SPEED = float(os.getenv("MAZE_STEP_LINEAR", "0.15"))       # m/s
ANGULAR_SPEED = float(os.getenv("MAZE_STEP_ANGULAR", "0.8"))      # rad/s
STEP_DURATION = float(os.getenv("MAZE_STEP_DURATION", "0.6"))     # seconds for UP/DOWN
TURN_DURATION = float(os.getenv("MAZE_TURN_DURATION", "6.0"))     # seconds for LEFT/RIGHT (1 cmd = 90°)
TURN_90_DURATION = float(os.getenv("MAZE_TURN_90_DURATION", "0.85"))
CELL_MOVE_DURATION = float(os.getenv("MAZE_CELL_MOVE_DURATION", "0.60"))
ACTION_MODE = os.getenv("MAZE_ACTION_MODE", "grid_absolute").strip().lower()
TOPIC = os.getenv("MAZE_CMD_VEL_TOPIC", "/cmd_vel")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL = "maze_actions"

# Simple mode action map.
# linear.x is flipped from ROS convention because the Mini Pupper controller
# treats negative linear.x as the physical forward direction.
ACTION_MAP = {
    "UP": (-LINEAR_SPEED, 0.0),   # negative = physical forward
    "DOWN": (LINEAR_SPEED, 0.0),  # positive = physical backward
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


class MazeBridgeNode(Node):
    def __init__(self):
        super().__init__("maze_ros_bridge")
        self.pub = self.create_publisher(Twist, TOPIC, 10)
        self.heading = 0
        self.get_logger().info(f"Publishing to {TOPIC}")
        self.get_logger().info(
            f"ACTION_MODE={ACTION_MODE} LINEAR={LINEAR_SPEED} ANGULAR={ANGULAR_SPEED}"
        )
        self.get_logger().info(
            f"STEP_DURATION={STEP_DURATION}s  TURN_DURATION={TURN_DURATION}s"
        )

    def publish_for_duration(self, linear_x: float, angular_z: float, duration_s: float) -> None:
        msg = Twist()
        msg.linear.x = linear_x
        msg.angular.z = angular_z
        self.pub.publish(msg)
        time.sleep(max(0.0, duration_s))
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

        self.publish_for_duration(LINEAR_SPEED, 0.0, CELL_MOVE_DURATION)
        return True

    def execute_action(self, action: str) -> bool:
        action = action.strip().upper()
        if action == "DONE":
            self.get_logger().info("DONE received, publishing stop.")
            self.pub.publish(Twist())
            return True

        if ACTION_MODE == "grid_absolute":
            return self.execute_grid_absolute_action(action)

        if action not in ACTION_MAP:
            self.get_logger().warn(f"Unknown action: {action!r} — ignored")
            return False

        lx, az = ACTION_MAP[action]
        # Use TURN_DURATION for left/right so one command = one 90-degree turn
        duration = TURN_DURATION if action in ("LEFT", "RIGHT") else STEP_DURATION
        self.get_logger().info(
            f"Action={action} linear.x={lx} angular.z={az} dur={duration}s"
        )
        self.publish_for_duration(lx, az, duration)
        return True


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
            except (json.JSONDecodeError, AttributeError):
                action = str(message["data"])

            node.execute_action(action)
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
