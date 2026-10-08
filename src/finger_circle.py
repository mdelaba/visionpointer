"""Webcam preview: a blue circle follows the thumb tip and turns green while pinched.

Use it to check pinch detection and tune --pinch-close / --pinch-open before using the full
pipeline. Also holds helpers shared by the other scripts (camera setup, hand metrics, pinch tracker).
Press q or Esc to quit. Exits automatically after --timeout seconds.
"""
import argparse
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "hand_landmarker.task"
WRIST, THUMB_TIP, INDEX_FINGER_TIP, MIDDLE_MCP = 0, 4, 8, 9
BLUE_BGR = (255, 0, 0)
GREEN_BGR = (0, 200, 0)
WINDOW = "VisionPointer"


def open_camera(index: int):
    """Open the camera as MJPG 1280x720@30 (more fingertip pixels and fps than the defaults)."""
    cap = cv2.VideoCapture(index)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)
    return cap


def camera_size(cap) -> list[int]:
    return [int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))]


def hand_metrics(lm, w, h):
    """Return (thumb tip pixel, pinch ratio) for one hand's landmarks.

    Pinch ratio = thumb-tip to index-tip distance / palm length (wrist to middle knuckle):
    small when pinched, larger when the fingers are apart.
    """
    px = lambda i: np.array([lm[i].x * w, lm[i].y * h])
    palm = max(np.linalg.norm(px(WRIST) - px(MIDDLE_MCP)), 1e-6)
    ratio = float(np.linalg.norm(px(THUMB_TIP) - px(INDEX_FINGER_TIP)) / palm)
    return tuple(px(THUMB_TIP)), ratio  # thumb tip: it stays put while the index finger closes on it


class PinchTracker:
    """Detects the open->pinched transition from the thumb/index ratio, with hysteresis."""

    def __init__(self, close_at, open_at, frames=2):
        self.close_at, self.open_at, self.frames = close_at, open_at, frames
        self.closed, self.below = False, 0

    def reset(self):
        self.closed, self.below = False, 0

    def __call__(self, ratio) -> bool:
        """Feed one frame's ratio; returns True on the frame a pinch is confirmed."""
        if self.closed:
            if ratio > self.open_at:
                self.closed = False
            return False
        self.below = self.below + 1 if ratio < self.close_at else 0
        if self.below >= self.frames:
            self.closed = True
            return True
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=300, help="max run time in seconds")
    parser.add_argument("--radius", type=int, default=20)
    parser.add_argument("--pinch-close", type=float, default=0.18, help="ratio below which a pinch starts")
    parser.add_argument("--pinch-open", type=float, default=0.23, help="ratio above which the pinch is released")
    parser.add_argument("--headless", action="store_true", help="no window; process 30 frames (for testing)")
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
            min_hand_detection_confidence=0.7,
            min_hand_presence_confidence=0.7,
            min_tracking_confidence=0.7,
        )
    )

    pinch = PinchTracker(args.pinch_close, args.pinch_open)
    start = time.monotonic()
    frames = detections = pinches = 0
    try:
        while time.monotonic() - start < args.timeout:
            ok, frame = cap.read()
            if not ok:
                print("Camera read failed", file=sys.stderr)
                return 1
            frame = cv2.flip(frame, 1)  # mirror so it behaves like a mirror
            h, w = frame.shape[:2]

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(image, int((time.monotonic() - start) * 1000))
            frames += 1

            status = "no hand"
            if result.hand_landmarks:
                lm = result.hand_landmarks[0]
                tip, ratio = hand_metrics(lm, w, h)
                if pinch(ratio):
                    pinches += 1
                    print(f"PINCH #{pinches} at t={time.monotonic() - start:.1f}s ratio={ratio:.2f}", flush=True)
                index = (int(lm[INDEX_FINGER_TIP].x * w), int(lm[INDEX_FINGER_TIP].y * h))
                cv2.circle(frame, index, 6, (255, 255, 255), -1)
                cv2.circle(frame, (int(tip[0]), int(tip[1])), args.radius, GREEN_BGR if pinch.closed else BLUE_BGR, -1)
                detections += 1
                status = f"{'PINCHED' if pinch.closed else 'open'}  ratio {ratio:.2f}  (close<{args.pinch_close} open>{args.pinch_open})"
            else:
                pinch.reset()

            if args.headless:
                if frames >= 30:
                    break
                continue
            cv2.putText(frame, status, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            cv2.imshow(WINDOW, frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        cap.release()
        landmarker.close()
        cv2.destroyAllWindows()

    print(f"frames={frames} detections={detections} pinches={pinches}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
