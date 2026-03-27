## Camera Setup & Testing

This guide covers non-ROS checks, a recommended Python virtual environment workflow (to avoid NumPy/OpenCV issues), and ROS 2 camera viewing.

Note: Written for **Mini Pupper 1** in our class setup. For **Mini Pupper 2** camera/stack differences, start from the official docs: [Mini Pupper ROS2 Guide](https://minipupperdocs.readthedocs.io/en/latest/guide/ROS2Guide.html).

---

## Recommended: Update the System (packages)

Before doing camera setup, it’s a good idea to update packages on the Mini Pupper.

On the **robot** (Ubuntu):

```bash
sudo apt update
sudo apt upgrade -y
sudo apt autoremove -y
```

---

## Recommended: Use a Python virtual environment (NumPy/OpenCV compatibility)

On the **robot** (Ubuntu), create and use a virtual environment for camera scripts:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip

python3 -m venv ~/camera-venv
source ~/camera-venv/bin/activate

python -m pip install --upgrade pip
python -m pip install numpy opencv-python
```

Tip: If you later open a new SSH session, re-activate with:

```bash
source ~/camera-venv/bin/activate
```

---

## 1) Non-ROS camera checks (on the robot)

List camera devices:

```bash
ls -l /dev/video*
```

If `v4l2-ctl` is available (install with `sudo apt install -y v4l-utils`):

```bash
v4l2-ctl --list-devices
v4l2-ctl --all -d /dev/video0
```

Quick stream test (if installed):

- With `ffmpeg`:

```bash
ffplay /dev/video0
```

(If `ffplay` isn’t installed: `sudo apt install -y ffmpeg`.)

---

## 2) Capture a raw frame → convert to PNG → copy to your laptop (Recommended test)

This is a good “sensor sanity check” when streaming tools are flaky. The goal is:

1) Capture **one raw frame**
2) Convert it to **PNG**
3) Transfer it to your laptop
4) Verify basic statistics show a real brightness range (example: `min 0`, `max 1023`, `mean 122`)

### Capture + convert (run on the robot, inside the venv)

```bash
source ~/camera-venv/bin/activate
python - <<'PY'
import numpy as np
import cv2

cap = cv2.VideoCapture(0)  # /dev/video0
ok, frame = cap.read()
cap.release()
if not ok:
    raise SystemExit("Failed to capture frame from /dev/video0")

# Save a PNG for quick inspection
cv2.imwrite("frame.png", frame)

# Print simple statistics to validate the sensor is producing data
arr = frame.astype(np.float32)
print("min", int(arr.min()))
print("max", int(arr.max()))
print("mean", float(arr.mean()))
PY
```

If you see values similar to:

```text
min 0
max 1023
mean 122
```

that’s a good sign the sensor is working and capturing a full brightness range.

### Copy `frame.png` to your laptop

From your **laptop** (macOS/Linux/Windows PowerShell), run:

```bash
scp minipupper1@<robot-ip-or-hostname>:~/frame.png .
```

Example:

```bash
scp minipupper1@10.170.8.209:~/frame.png .
```

---

## 3) ROS 2 camera node (Generic approach)

If your robot image includes `v4l2_camera`:

```bash
ros2 run v4l2_camera v4l2_camera_node --ros-args -p video_device:=/dev/video0
```

Then on a machine with GUI (often your laptop), view images:

```bash
ros2 run rqt_image_view rqt_image_view
```

or:

```bash
ros2 topic list | grep image
ros2 run image_tools showimage --ros-args -r image:=/image_raw
```

If you don’t know which camera package is installed, start by inspecting topics:

```bash
ros2 topic list
ros2 topic list | grep -E "image|camera"
```
