import cv2
import numpy as np
from pupil_apriltags import Detector
import math
import platform
import argparse

def rvec_to_rpy_degrees(rvec):
    R, _ = cv2.Rodrigues(rvec)
    # ZYX yaw-pitch-roll, R = Rz*Ry*Rx
    yaw = math.atan2(R[1,0], R[0,0])
    pitch = math.atan2(-R[2,0], math.sqrt(R[2,1]**2 + R[2,2]**2))
    roll = math.atan2(R[2,1], R[2,2])
    return (math.degrees(roll), math.degrees(pitch), math.degrees(yaw))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Print pose to terminal instead of showing a window")
    args = parser.parse_args()

    system = platform.system()

    # ---- Camera setup ----
    picam2 = None
    cap = None

    if system == "Linux":
        from picamera2 import Picamera2
        w, h = 640, 480
        fx = fy = 450.0
        picam2 = Picamera2()
        picam2.configure(picam2.create_preview_configuration(
            main={"format": "RGB888", "size": (w, h)}
        ))
        picam2.start()
    else:
        cam_index = 0
        w, h = 1280, 720
        fx = fy = 900.0
        if system == "Windows":
            cap = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)
        else:  # macOS
            cap = cv2.VideoCapture(cam_index, cv2.CAP_AVFOUNDATION)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        if not cap.isOpened():
            raise RuntimeError("Could not open camera. Try cam_index=1 or 2.")

    # ---- AprilTag detector ----
    detector = Detector(
        families="tag36h11",
        nthreads=2,
        quad_decimate=2.0,
        quad_sigma=0.0,
        refine_edges=1,
        decode_sharpening=0.25,
        debug=0
    )

    # ---- Pose parameters ----
    tag_size_m = 0.152  # <-- set to the physical printed size (meters)
    cx = w / 2.0
    cy = h / 2.0

    print("Press ESC to quit." if not args.headless else "Running headless. Press Ctrl+C to quit.")
    while True:
        if picam2 is not None:
            rgb = picam2.capture_array()
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        else:
            ok, frame = cap.read()
            if not ok:
                break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        tags = detector.detect(
            gray,
            estimate_tag_pose=True,
            camera_params=(fx, fy, cx, cy),
            tag_size=tag_size_m
        )

        best = None
        if tags:
            best = max(tags, key=lambda t: t.decision_margin)

        if best is not None:
            tag_type = "tag36h11"
            tag_id = best.tag_id

            tx, ty, tz = best.pose_t.flatten().tolist()

            R = best.pose_R
            yaw = math.atan2(R[1,0], R[0,0])
            pitch = math.atan2(-R[2,0], math.sqrt(R[2,1]**2 + R[2,2]**2))
            roll = math.atan2(R[2,1], R[2,2])
            roll, pitch, yaw = map(math.degrees, (roll, pitch, yaw))

            msg1 = f"Type: {tag_type}  ID: {tag_id}"
            msg2 = f"X: {tx:.3f} m  Y: {ty:.3f} m  Z: {tz:.3f} m"
            msg3 = f"roll: {roll:.1f}  pitch: {pitch:.1f}  yaw: {yaw:.1f}"

            if args.headless:
                print(f"{msg1} | {msg2} | {msg3}")
            else:
                cv2.putText(frame, msg1, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2)
                cv2.putText(frame, msg2, (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2)
                cv2.putText(frame, msg3, (20,110), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2)

                corners = best.corners.astype(int)
                for i in range(4):
                    p0 = tuple(corners[i])
                    p1 = tuple(corners[(i+1) % 4])
                    cv2.line(frame, p0, p1, (0,255,0), 2)

        if not args.headless:
            cv2.imshow("AprilTag Pose (Python)", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                break

    if picam2 is not None:
        picam2.stop()
    if cap is not None:
        cap.release()
    if not args.headless:
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
