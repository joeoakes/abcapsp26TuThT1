# ros_bridge_node.py

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from fastapi import FastAPI
from pydantic import BaseModel
import threading

app = FastAPI()

class MoveRequest(BaseModel):
    action: str
    x: int
    y: int
    session_id: str


class ROSBridge(Node):
    def __init__(self):
        super().__init__('maze_ros_bridge')
        self.publisher = self.create_publisher(Twist, '/cmd_vel', 10)
        self.get_logger().info("Publishing to /cmd_vel")

    def send_cmd(self, action: str):
        msg = Twist()

        # ---- TRANSLATION LAYER ----
        if action == "UP":
            msg.linear.x = 0.2
        elif action == "DOWN":
            msg.linear.x = -0.2
        elif action == "LEFT":
            msg.angular.z = 1.0
        elif action == "RIGHT":
            msg.angular.z = -1.0
        elif action == "DONE":
            msg.linear.x = 0.0
            msg.angular.z = 0.0

        self.publisher.publish(msg)


ros_node = None


@app.post("/move")
def move(req: MoveRequest):
    global ros_node
    ros_node.send_cmd(req.action)
    return {"status": "ok"}


def ros_spin():
    rclpy.spin(ros_node)


def main():
    global ros_node
    rclpy.init()
    ros_node = ROSBridge()

    thread = threading.Thread(target=ros_spin, daemon=True)
    thread.start()

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5050)


if __name__ == "__main__":
    main()
