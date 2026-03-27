## Mini Pupper 1 (Robot) Docs

These docs explain how to connect to **Mini Pupper 1**, drive it with **ROS 2**, and set up/test the **camera**.

We primarily use **Ubuntu Linux**, but the connection/IP/SSH steps include **macOS** and **Windows** options too.

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

