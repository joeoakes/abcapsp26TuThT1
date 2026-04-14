"""
ros_bridge_node.py
==================
ROS 2 node that listens on a Redis channel for maze actions and publishes
geometry_msgs/Twist to /cmd_vel.

Run this inside your ROS 2 environment:
    ros2 run <your_pkg> ros_bridge_node
    # or just:
    python3 ros_bridge_node.py

Tuning env vars:
    MAZE_STEP_LINEAR   - forward/back speed in m/s   (default 0.15)
    MAZE_STEP_ANGULAR  - turn speed in rad/s          (default 0.8)
    MAZE_STEP_DURATION - how long to drive per step   (default 0.6 s)
    REDIS_HOST         - Redis host                   (default localhost)
    REDIS_PORT         - Redis port                   (default 6379)
    MAZE_CMD_VEL_TOPIC - topic name                   (default /cmd_vel)
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
LINEAR_SPEED   = float(os.getenv("MAZE_STEP_LINEAR",   "0.15"))   # m/s
ANGULAR_SPEED  = float(os.getenv("MAZE_STEP_ANGULAR",  "0.8"))    # rad/s
STEP_DURATION  = float(os.getenv("MAZE_STEP_DURATION", "0.6"))    # seconds
TOPIC          = os.getenv("MAZE_CMD_VEL_TOPIC", "/cmd_vel")
REDIS_HOST     = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL  = "maze:ros:move"

# Map maze action strings to (linear.x, angular.z)
ACTION_MAP = {
    "UP":    ( LINEAR_SPEED,  0.0),           # forward
    "DOWN":  (-LINEAR_SPEED,  0.0),           # backward
    "RIGHT": ( 0.0,          -ANGULAR_SPEED), # turn right (ROS: negative z = clockwise)
    "LEFT":  ( 0.0,           ANGULAR_SPEED), # turn left
}


# ---------------------------------------------------------------------------
# ROS 2 node
# ---------------------------------------------------------------------------
class MazeBridgeNode(Node):
    def __init__(self):
        super().__init__("maze_ros_bridge")
        self.pub = self.create_publisher(Twist, TOPIC, 10)
        self.get_logger().info(f"Publishing to {TOPIC}")

    def execute_action(self, action: str) -> bool:
        """Publish a Twist for STEP_DURATION seconds, then stop. Returns True if known action."""
        action = action.strip().upper()
        if action not in ACTION_MAP:
            self.get_logger().warn(f"Unknown action: {action!r} — ignored")
            return False

        lx, az = ACTION_MAP[action]
        self.get_logger().info(f"Action={action}  linear.x={lx}  angular.z={az}  dur={STEP_DURATION}s")

        # Drive
        msg = Twist()
        msg.linear.x  = lx
        msg.angular.z = az
        self.pub.publish(msg)
        time.sleep(STEP_DURATION)

        # Stop
        self.pub.publish(Twist())   # all-zeros = stop
        return True


# ---------------------------------------------------------------------------
# Main: Redis subscriber loop
# ---------------------------------------------------------------------------
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
                action  = payload.get("action", "")
            except (json.JSONDecodeError, AttributeError):
                action = str(message["data"])   # plain string fallback

            node.execute_action(action)

            # Let ROS process callbacks between steps
            rclpy.spin_once(node, timeout_sec=0.0)

    except KeyboardInterrupt:
        pass
    finally:
        pubsub.unsubscribe()
        node.pub.publish(Twist())   # safety stop on exit
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
