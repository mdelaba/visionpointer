"""4-point calibration + fullscreen blue-circle pointer.

Calibration: point at each on-screen crosshair and press SPACE; 15 fingertip samples are
averaged per corner and a perspective matrix camera->screen is solved and saved.
Run: after calibration (or when calibration.json exists) a blue circle follows the mapped
fingertip position on a fullscreen black canvas.

Keys: SPACE = sample corner, c = recalibrate, q/Esc = quit. Exits after --timeout seconds.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from finger_circle import BLUE_BGR, MODEL_PATH, camera_size, hand_metrics, open_camera

CALIB_PATH = Path(__file__).resolve().parent.parent / "calibration.json"
WINDOW = "VisionPointer"
MARGIN = 0.08  # crosshairs sit this fraction in from the screen edges so they are reachable
SAMPLES = 15
SMOOTHING = 0.5  # EMA weight of the newest point


def screen_size() -> tuple[int, int]:
    try:
        from screeninfo import get_monitors

        m = get_monitors()[0]
        return m.width, m.height
    except Exception:
        return 1920, 1080


def read_hand(landmarker, cap, t0, cam_size, out=None):
    """Return (fingertip camera pixel, pinch ratio), or (None, None) if no hand.

    Pinch ratio = thumb-tip to index-tip distance / palm length (wrist to middle knuckle):
    roughly 0.1-0.25 when pinched, much larger when the hand is open.
    If out (a dict) is given it receives the raw frame and the index tip pixel (for a preview window).
    """
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError("Camera read failed")
    h, w = frame.shape[:2]
    cam_size[:] = [w, h]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect_for_video(image, int((time.monotonic() - t0) * 1000))
    if out is not None:
        out.update(frame=frame, index=None)
    if not result.hand_landmarks:
        return None, None
    lm = result.hand_landmarks[0]
    if out is not None:
        out["index"] = (int(lm[8].x * w), int(lm[8].y * h))
    return hand_metrics(lm, w, h)


def fingertip(landmarker, cap, t0, cam_size):
    """Return the raw (unmirrored) fingertip camera pixel, or None if no hand/frame."""
    return read_hand(landmarker, cap, t0, cam_size)[0]


def draw_crosshair(canvas, pt, text):
    x, y = int(pt[0]), int(pt[1])
    cv2.line(canvas, (x - 30, y), (x + 30, y), (0, 0, 255), 3)
    cv2.line(canvas, (x, y - 30), (x, y + 30), (0, 0, 255), 3)
    cv2.circle(canvas, (x, y), 18, (0, 0, 255), 2)
    cv2.putText(canvas, text, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)


def calibrate(landmarker, cap, t0, sw, sh, deadline):
    cam_size = camera_size(cap)
    corners = [
        (sw * MARGIN, sh * MARGIN),
        (sw * (1 - MARGIN), sh * MARGIN),
        (sw * (1 - MARGIN), sh * (1 - MARGIN)),
        (sw * MARGIN, sh * (1 - MARGIN)),
    ]
    names = ["top-left", "top-right", "bottom-right", "bottom-left"]
    cam_pts = []
    for i, (corner, name) in enumerate(zip(corners, names)):
        samples, sampling = [], False
        while len(samples) < SAMPLES:
            if time.monotonic() > deadline:
                return None
            canvas = np.zeros((sh, sw, 3), np.uint8)
            msg = f"{i + 1}/4 point at the {name} cross"
            msg += " - sampling..." if sampling else " and press SPACE"
            draw_crosshair(canvas, corner, msg)
            cv2.imshow(WINDOW, canvas)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                return None
            if key == ord(" "):
                sampling = True
            pt = fingertip(landmarker, cap, t0, cam_size)
            if sampling:
                if pt is None:
                    samples.clear()  # require an uninterrupted run of detections
                else:
                    samples.append(pt)
        cam_pts.append(np.mean(samples, axis=0))
    H = cv2.getPerspectiveTransform(np.float32(cam_pts), np.float32(corners))
    CALIB_PATH.write_text(json.dumps({"H": H.tolist(), "screen": [sw, sh], "cam": cam_size}))
    print(f"Saved {CALIB_PATH}")
    return H


def load_calibration(sw, sh, cam):
    """Calibration is only valid for the same screen size and camera resolution."""
    try:
        data = json.loads(CALIB_PATH.read_text())
        if data["screen"] == [sw, sh] and data.get("cam") == cam:
            return np.array(data["H"], dtype=np.float64)
    except (OSError, KeyError, ValueError):
        pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=300, help="max run time in seconds")
    parser.add_argument("--recalibrate", action="store_true")
    parser.add_argument("--radius", type=int, default=20)
    args = parser.parse_args()

    if not MODEL_PATH.exists():
        print(f"Missing model: {MODEL_PATH}", file=sys.stderr)
        return 1
    cap = open_camera(args.camera)
    if not cap.isOpened():
        print(f"Cannot open camera {args.camera}", file=sys.stderr)
        return 1
    landmarker = vision.HandLandmarker.create_from_options(
        vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
        )
    )

    sw, sh = screen_size()
    t0 = time.monotonic()
    deadline = t0 + args.timeout
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cam_size = [1, 1]
    try:
        H = None if args.recalibrate else load_calibration(sw, sh, camera_size(cap))
        smoothed = None
        while time.monotonic() < deadline:
            if H is None:
                H = calibrate(landmarker, cap, t0, sw, sh, deadline)
                if H is None:
                    break
            canvas = np.zeros((sh, sw, 3), np.uint8)
            pt = fingertip(landmarker, cap, t0, cam_size)
            if pt is not None:
                mapped = cv2.perspectiveTransform(np.float32([[pt]]), H)[0][0]
                mapped = np.clip(mapped, [0, 0], [sw - 1, sh - 1])
                smoothed = mapped if smoothed is None else SMOOTHING * mapped + (1 - SMOOTHING) * smoothed
                cv2.circle(canvas, (int(smoothed[0]), int(smoothed[1])), args.radius, BLUE_BGR, -1)
            else:
                smoothed = None
            cv2.putText(canvas, "c = recalibrate, q = quit", (40, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (120, 120, 120), 2)
            cv2.imshow(WINDOW, canvas)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("c"):
                H = None
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        cap.release()
        landmarker.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
