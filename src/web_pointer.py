"""Point at web elements: fullscreen Chromium + calibrated thumb tip + snapping + pinch select.

Run calibrate_pointer.py first (it writes calibration.json). Pinch (thumb to index) and release to
select the element you point at and keep it highlighted; pinch empty space to clear. Pinch and drag
vertically to scroll (the circle turns orange) or horizontally to go back/forward. Pinch and hold still to click. Selections are printed
as `VP_SELECT {json}` lines and written to the state dir (see selection_store.py). Press Esc in the browser to quit; exits after --timeout seconds.
"""
import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".browsers"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from mediapipe.tasks.python import BaseOptions, vision  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import selection_store  # noqa: E402
from calibrate_pointer import camera_size, load_calibration, open_camera, read_hand, screen_size  # noqa: E402
from finger_circle import MODEL_PATH, PinchTracker  # noqa: E402

INJECT_JS = (Path(__file__).resolve().parent / "vp_inject.js").read_text()
TEST_PAGE = ROOT / "testpage" / "index.html"


class SpikeRejector:
    """Median of the last 3 points, then hold the last position across implausible jumps.

    A jump bigger than max_jump is ignored unless it persists for `patience` frames
    (then it is accepted as a real fast move or re-detection).
    """

    def __init__(self, max_jump, patience=3):
        self.max_jump, self.patience = max_jump, patience
        self.reset()

    def reset(self):
        self.recent, self.last, self.rejected = [], None, 0

    def __call__(self, p):
        self.recent = (self.recent + [np.asarray(p, dtype=np.float64)])[-3:]
        m = np.median(self.recent, axis=0)
        if self.last is not None and np.linalg.norm(m - self.last) > self.max_jump:
            self.rejected += 1
            if self.rejected < self.patience:
                return self.last
        self.rejected, self.last = 0, m
        return m


class OneEuroFilter:
    """Adaptive low-pass: smooth a lot when slow (kills jitter), little when fast (low lag)."""

    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * np.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self):
        self.x = self.dx = self.t = None

    def __call__(self, x, t):
        x = np.asarray(x, dtype=np.float64)
        if self.x is None:
            self.x, self.dx, self.t = x, np.zeros_like(x), t
            return x
        dt = max(t - self.t, 1e-3)
        dx = (x - self.x) / dt
        self.dx = self.dx + self._alpha(self.d_cutoff, dt) * (dx - self.dx)
        cutoff = self.min_cutoff + self.beta * np.linalg.norm(self.dx)
        self.x = self.x + self._alpha(cutoff, dt) * (x - self.x)
        self.t = t
        return self.x


class PinchGesture:
    """Turns pinch frames into actions.

    Pinch+release selects. Pinch+hold (held still for hold_s) clicks. Pinch+vertical drag scrolls;
    pinch+horizontal drag navigates (drag right = back, left = forward, like swiping a touchscreen).

    step() returns ("select", target) on release, ("click", target) once the pinch has been held
    still for hold_s, ("scroll_start", pos) then ("scroll", wheel_delta) while dragging vertically,
    or ("back", None) / ("forward", None) once.
    Scrolling follows the hand like a touchscreen: hand up -> content up (wheel delta positive).
    """

    def __init__(self, threshold, gain, swipe=0.0, hold_s=0.0):
        self.threshold, self.gain, self.swipe, self.hold_s = threshold, gain, swipe, hold_s
        self.reset()

    def reset(self):
        self.active = self.scrolling = self.navigated = self.clicked = False
        self.target, self.start, self.last_y, self.start_t = None, (0.0, 0.0), 0.0, 0.0

    def step(self, confirmed, closed, pos, target, now):
        actions = []
        if confirmed:
            self.active, self.scrolling, self.navigated, self.clicked, self.target = True, False, False, False, target
            self.start, self.last_y, self.start_t = (pos[0], pos[1]), pos[1], now
        elif self.active:
            if closed:
                dx, dy = pos[0] - self.start[0], pos[1] - self.start[1]
                if not (self.scrolling or self.navigated or self.clicked):
                    if abs(dy) > self.threshold and abs(dy) >= abs(dx):
                        self.scrolling = True
                        actions.append(("scroll_start", pos))
                    elif self.swipe > 0 and abs(dx) > self.swipe and abs(dx) > 2 * abs(dy):
                        self.navigated = True
                        actions.append(("back" if dx > 0 else "forward", None))
                    elif self.hold_s > 0 and now - self.start_t >= self.hold_s:
                        self.clicked = True
                        actions.append(("click", self.target))
                if self.scrolling:
                    actions.append(("scroll", -(pos[1] - self.last_y) * self.gain))
                    self.last_y = pos[1]
            else:
                if not (self.scrolling or self.navigated or self.clicked):
                    actions.append(("select", self.target))
                self.active = self.scrolling = self.navigated = self.clicked = False
        return actions


def ensure_fullscreen(page, sw, sh, wait=5.0):
    """Pointer mapping assumes the page fills the screen; on Hyprland, ask for fullscreen."""
    def size():
        return tuple(page.evaluate("[innerWidth, innerHeight]"))

    if size() != (sw, sh) and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        subprocess.run(["hyprctl", "dispatch", "fullscreen", "0"], timeout=5, capture_output=True)
    end = time.monotonic() + wait
    while size() != (sw, sh) and time.monotonic() < end:
        time.sleep(0.1)
    if size() != (sw, sh):
        print(f"Warning: viewport {size()} != screen {(sw, sh)}; make the window fullscreen.", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=300, help="max run time in seconds")
    parser.add_argument("--url", default=TEST_PAGE.as_uri())
    parser.add_argument("--radius", type=int, default=50, help="snap radius in px")
    parser.add_argument("--no-snap", action="store_true", help="only exact hits count")
    parser.add_argument("--dwell-ms", type=int, default=0, help="also select after holding this long (0 = off, pinch only)")
    parser.add_argument("--pinch-close", type=float, default=0.18, help="thumb-index/palm ratio below which a pinch starts")
    parser.add_argument("--pinch-open", type=float, default=0.23, help="ratio above which the pinch is released")
    parser.add_argument("--pinch-lookback", type=float, default=0.25, help="seconds: select where you pointed this long ago (the pinch moves the fingertip)")
    parser.add_argument("--smooth", type=float, default=0.45, help="base cutoff Hz: lower = steadier but laggier")
    parser.add_argument("--confidence", type=float, default=0.7, help="MediaPipe hand detection/presence/tracking threshold")
    parser.add_argument("--debug-log", type=Path, help="write per-frame CSV (raw camera, mapped, filtered positions)")
    parser.add_argument("--max-jump", type=float, default=300, help="ignore single-frame jumps larger than this many screen px")
    parser.add_argument("--smooth-beta", type=float, default=0.01, help="speed term: higher = less lag when moving fast")
    parser.add_argument("--scroll-threshold", type=float, default=40, help="screen px of vertical movement while pinched before it becomes a scroll")
    parser.add_argument("--scroll-gain", type=float, default=1.5, help="scroll distance per px of hand movement")
    parser.add_argument("--swipe-threshold", type=float, default=250, help="screen px of horizontal movement while pinched that triggers back/forward (0 = off)")
    parser.add_argument("--click-hold", type=float, default=0.6, help="seconds to hold a pinch still to click (0 = off)")
    parser.add_argument("--hit-test", action="store_true", help="run the test page's scored hit test")
    args = parser.parse_args()

    sw, sh = screen_size()
    if not MODEL_PATH.exists():
        print(f"Missing model: {MODEL_PATH}", file=sys.stderr)
        return 1
    cap = open_camera(args.camera)
    if not cap.isOpened():
        print(f"Cannot open camera {args.camera}", file=sys.stderr)
        return 1
    H = load_calibration(sw, sh, camera_size(cap))
    if H is None:
        cap.release()
        print("No calibration for this screen size and camera resolution; run calibrate_pointer.py first.", file=sys.stderr)
        return 1
    landmarker = vision.HandLandmarker.create_from_options(
        vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=args.confidence,
            min_hand_presence_confidence=args.confidence,
            min_tracking_confidence=args.confidence,
        )
    )

    url = args.url + ("?hit=1" if args.hit_test and args.url == TEST_PAGE.as_uri() else "")
    quit_flag = []

    def on_console(msg):
        text = msg.text
        if not text.startswith("VP_"):
            return
        print(text, flush=True)
        try:
            if text == "VP_QUIT":
                quit_flag.append(1)
            elif text == "VP_CLEAR":
                selection_store.clear_selection()
            elif text.startswith("VP_SELECT "):
                selection_store.write_selection(json.loads(text[len("VP_SELECT "):]))
        except (OSError, ValueError) as e:
            print(f"Could not save selection: {e}", file=sys.stderr)

    selection_store.clear_selection()  # a previous session's selection is no longer highlighted

    t0 = time.monotonic()
    deadline = t0 + args.timeout
    cam_size = camera_size(cap)
    log = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--kiosk"], timeout=30000)
            context = browser.new_context(no_viewport=True)
            context.add_init_script(INJECT_JS)
            page = context.new_page()
            page.on("console", on_console)
            page.goto(url, timeout=30000)
            ensure_fullscreen(page, sw, sh)
            page.evaluate(
                "o => window.__vp.configure(o)",
                {"radius": args.radius, "snap": not args.no_snap, "dwellMs": args.dwell_ms},
            )

            smoother = OneEuroFilter(args.smooth, args.smooth_beta)
            spikes = SpikeRejector(args.max_jump)
            pinch = PinchTracker(args.pinch_close, args.pinch_open)
            gesture = PinchGesture(args.scroll_threshold, args.scroll_gain, args.swipe_threshold, args.click_hold)
            history = collections.deque()  # (time, fx, fy) smoothed screen fractions
            if args.debug_log:
                log = open(args.debug_log, "w")
                log.write("t,detected,cam_x,cam_y,mapped_x,mapped_y,filt_x,filt_y,pinch\n")
            while time.monotonic() < deadline and not quit_flag and not page.is_closed():
                pt, ratio = read_hand(landmarker, cap, t0, cam_size)
                if pt is None:
                    if log:
                        log.write(f"{time.monotonic() - t0:.3f},0,,,,,,,\n")
                    smoother.reset()
                    spikes.reset()
                    pinch.reset()
                    gesture.reset()
                    history.clear()
                    page.evaluate("window.__vp.update(null, null)")
                    continue
                mapped = cv2.perspectiveTransform(np.float32([[pt]]), H)[0][0]
                mapped = np.clip(mapped, [0, 0], [sw - 1, sh - 1])
                now = time.monotonic()
                smoothed = smoother(spikes(mapped), now)
                if log:
                    log.write(f"{now - t0:.3f},1,{pt[0]:.1f},{pt[1]:.1f},{mapped[0]:.1f},{mapped[1]:.1f},{smoothed[0]:.1f},{smoothed[1]:.1f},{ratio:.3f}\n")
                fx, fy = float(smoothed[0] / sw), float(smoothed[1] / sh)
                history.append((now, fx, fy))
                while history and now - history[0][0] > 1.5:
                    history.popleft()
                # scale by the live viewport so resizing/fullscreen mid-run stays correct
                page.evaluate(
                    "([fx, fy, p]) => window.__vp.update(fx * innerWidth, fy * innerHeight, p)",
                    [fx, fy, "scroll" if gesture.scrolling else "click" if gesture.clicked else pinch.closed],
                )
                confirmed = pinch(ratio)
                # closing the pinch moves the fingertip, so select where it was pointing just before
                _, px, py = min(history, key=lambda h: abs(h[0] - (now - args.pinch_lookback)))
                for action, value in gesture.step(confirmed, pinch.closed, smoothed, (px, py), now):
                    if action == "select":
                        page.evaluate("([fx, fy]) => window.__vp.selectAt(fx * innerWidth, fy * innerHeight)", list(value))
                    elif action == "click":
                        # select (sticky highlight) then send a real mouse click at the element's centre
                        c = page.evaluate("([fx, fy]) => window.__vp.selectAt(fx * innerWidth, fy * innerHeight)", list(value))
                        if c:
                            page.mouse.click(c[0], c[1])
                    elif action in ("back", "forward"):
                        selection_store.clear_selection()
                        (page.go_back if action == "back" else page.go_forward)(timeout=10000)
                    elif action == "scroll_start":
                        page.mouse.move(float(value[0]), float(value[1]))  # wheel events go to what is under the mouse
                    elif action == "scroll":
                        page.mouse.wheel(0, float(value))
            browser.close()
    except Exception as e:  # camera/browser failures should end cleanly, not hang
        if "has been closed" in str(e):  # the window was closed (Esc/quit) mid-frame: a normal exit
            return 0
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        if log:
            log.close()
        cap.release()
        landmarker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
