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


SHOT_MAX = 1568  # longest side sent to Claude, in px
SHOTS_KEPT = 5


def capture_selection(page, point):
    """Screenshot the page with the selected element boxed and the pointed spot marked.

    point is where the user pointed, as screen fractions. Returns the screenshot record that
    selection_store.attach_screenshot stores (file paths plus the element box and pointer position in
    image pixels and as 0-1 fractions), or None when nothing is selected.
    """
    sel = selection_store.read_selection()
    info = page.evaluate("() => { const r = window.__vp.selectedRect(); return r && { r, vw: innerWidth, vh: innerHeight }; }")
    if not sel or not info:
        return None, None
    page.evaluate("document.documentElement.setAttribute('data-vp-hide', '1')")  # no circle/highlight in the picture
    try:
        png = page.screenshot(type="png", timeout=5000)
    finally:
        page.evaluate("document.documentElement.removeAttribute('data-vp-hide')")
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    vw, vh = info["vw"], info["vh"]
    sx, sy = w / vw, h / vh
    x0, y0, x1, y1 = info["r"]
    box = [x0 * sx, y0 * sy, x1 * sx, y1 * sy]
    clipped = [max(box[0], 0), max(box[1], 0), min(box[2], w), min(box[3], h)]
    partial = clipped != box
    pointer = [point[0] * w, point[1] * h]

    def shrink(image):
        k = min(1.0, SHOT_MAX / max(image.shape[:2]))
        return (cv2.resize(image, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else image), k

    clean, k = shrink(img)
    annotated = clean.copy()
    b = [int(v * k) for v in clipped]
    px_, py_ = int(pointer[0] * k), int(pointer[1] * k)
    cv2.rectangle(annotated, (b[0], b[1]), (b[2], b[3]), (0, 0, 255), 3)
    cv2.drawMarker(annotated, (px_, py_), (0, 0, 255), cv2.MARKER_CROSS, 28, 3)
    margin = int(24 * k)
    crop = clean[max(b[1] - margin, 0):min(b[3] + margin, clean.shape[0]), max(b[0] - margin, 0):min(b[2] + margin, clean.shape[1])]
    if crop.size == 0:
        crop = clean

    out = selection_store.SCREENSHOT_DIR
    out.mkdir(parents=True, exist_ok=True)
    stamp = f"{int(time.time() * 1000)}"
    paths = {}
    for name, image in (("annotated", annotated), ("crop", crop), ("clean", clean)):
        paths[name] = str(out / f"{stamp}_{name}.png")
        cv2.imwrite(paths[name], image)
    for old in sorted(out.glob("*_annotated.png"))[:-SHOTS_KEPT]:  # keep only the last few selections on disk
        for f in out.glob(old.name.split("_")[0] + "_*.png"):
            f.unlink(missing_ok=True)
    H, W = clean.shape[:2]
    return {
        **paths,
        "image_size": [W, H],
        "element_box": [round(v) for v in b],
        "element_box_norm": [round(b[0] / W, 3), round(b[1] / H, 3), round(b[2] / W, 3), round(b[3] / H, 3)],
        "element_partly_offscreen": partial,
        "pointer": [px_, py_],
        "pointer_norm": [round(px_ / W, 3), round(py_ / H, 3)],
        "viewport": [vw, vh],
        "device_pixel_ratio": round(sx, 3),
    }, sel["selected_at"]


PREVIEW_WINDOW = "VisionPointer"
PREVIEW_W = 320


def show_preview(seen, tip, closed):
    """Small mirrored webcam window: white dot on the index tip, circle on the thumb tip (green while pinched)."""
    if not getattr(show_preview, "made", False):  # GUI_NORMAL: no Qt toolbar (zoom/save/properties buttons) or status bar
        cv2.namedWindow(PREVIEW_WINDOW, cv2.WINDOW_GUI_NORMAL | cv2.WINDOW_AUTOSIZE)
        show_preview.made = True
    frame = cv2.flip(seen["frame"], 1)
    h, w = frame.shape[:2]
    if tip is not None:
        cv2.circle(frame, (int(w - tip[0]), int(tip[1])), 30, (0, 200, 0) if closed else (255, 0, 0), -1)
        if seen.get("index"):
            cv2.circle(frame, (w - seen["index"][0], seen["index"][1]), 8, (255, 255, 255), -1)
    cv2.imshow(PREVIEW_WINDOW, cv2.resize(frame, (PREVIEW_W, PREVIEW_W * h // w), interpolation=cv2.INTER_AREA))
    cv2.waitKey(1)


def capture_page(page, want_shot, shots_on):
    """Describe the current page (and screenshot it when allowed); used when the user has nothing selected."""
    page.evaluate("document.documentElement.setAttribute('data-vp-hide', '1')")  # hidden overlays are excluded from innerText too
    try:
        info = page.evaluate(
            "() => ({ url: location.href, title: document.title, viewport: [innerWidth, innerHeight],"
            " scroll: [scrollX, scrollY], page_height: document.documentElement.scrollHeight,"
            " text: (document.body ? document.body.innerText : '').trim().slice(0, 3000) })"
        )
        png = page.screenshot(type="png", timeout=5000) if want_shot and shots_on else None
    finally:
        page.evaluate("document.documentElement.removeAttribute('data-vp-hide')")
    if png is not None:
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        k = min(1.0, SHOT_MAX / max(img.shape[:2]))
        if k < 1:
            img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        out = selection_store.SCREENSHOT_DIR
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*_page.png"):
            old.unlink(missing_ok=True)
        path = out / f"{int(time.time() * 1000)}_page.png"
        cv2.imwrite(str(path), img)
        info.update(screenshot=str(path), image_size=[img.shape[1], img.shape[0]])
    elif want_shot:
        info["screenshot_unavailable"] = "web_pointer must be started with --screenshots (off by default for privacy)"
    return info


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
    parser.add_argument("--confidence", type=float, default=0.8, help="MediaPipe hand detection/presence/tracking threshold")
    parser.add_argument("--debug-log", type=Path, help="write per-frame CSV (raw camera, mapped, filtered positions)")
    parser.add_argument("--max-jump", type=float, default=300, help="ignore single-frame jumps larger than this many screen px")
    parser.add_argument("--smooth-beta", type=float, default=0.01, help="speed term: higher = less lag when moving fast")
    parser.add_argument("--scroll-threshold", type=float, default=40, help="screen px of vertical movement while pinched before it becomes a scroll")
    parser.add_argument("--scroll-gain", type=float, default=1.2, help="scroll distance per px of hand movement")
    parser.add_argument("--swipe-threshold", type=float, default=250, help="screen px of horizontal movement while pinched that triggers back/forward (0 = off)")
    parser.add_argument("--click-hold", type=float, default=0.6, help="seconds to hold a pinch still to click (0 = off)")
    parser.add_argument("--voice", action="store_true", help="talk to Claude about what you point at (listens only while a hand is visible)")
    parser.add_argument("--voice-model", default="haiku", help="Claude model for voice answers (haiku is fastest; e.g. sonnet for deeper answers)")
    parser.add_argument("--voice-silence", type=float, default=0.8, help="seconds of silence that end your question")
    parser.add_argument("--screenshots", action="store_true", help="save a screenshot with each selection so Claude can look at it when a question needs it (off by default: screenshots can contain private page content)")
    parser.add_argument("--preview", action="store_true", help="show a small webcam window with the hand tracking (for recording demos)")
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

    selection_store.clear_selection()  # also deletes old screenshots; a previous session's selection is no longer highlighted

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

            voice = None
            if args.voice:
                from voice import VoiceAssistant

                voice = VoiceAssistant(args.voice_model, args.voice_silence)
                voice.start()
            shown_status = None

            def shoot(point):
                if not args.screenshots:
                    return
                try:
                    shot, selected_at = capture_selection(page, point)
                    if shot:
                        selection_store.attach_screenshot(selected_at, shot)
                except Exception as e:  # a failed screenshot must never break pointing
                    print(f"Screenshot failed: {e}", file=sys.stderr)

            smoother = OneEuroFilter(args.smooth, args.smooth_beta)
            spikes = SpikeRejector(args.max_jump)
            pinch = PinchTracker(args.pinch_close, args.pinch_open)
            gesture = PinchGesture(args.scroll_threshold, args.scroll_gain, args.swipe_threshold, args.click_hold)
            history = collections.deque()  # (time, fx, fy) smoothed screen fractions
            if args.debug_log:
                log = open(args.debug_log, "w")
                log.write("t,detected,cam_x,cam_y,mapped_x,mapped_y,filt_x,filt_y,pinch\n")
            while time.monotonic() < deadline and not quit_flag and not page.is_closed():
                seen = {} if args.preview else None
                pt, ratio = read_hand(landmarker, cap, t0, cam_size, seen)
                req = selection_store.take_page_request()
                if req:  # a reader (the MCP server) asked what is on the page
                    try:
                        info = capture_page(page, req.get("screenshot"), args.screenshots)
                    except Exception as e:
                        info = {"error": str(e)}
                    selection_store._write_atomic(selection_store.PAGE_FILE, json.dumps({**info, "requested_at": req["requested_at"]}))
                if voice:
                    if pt is not None:
                        voice.hand_seen()
                    if (voice.status, voice.caption) != shown_status:
                        shown_status = (voice.status, voice.caption)
                        page.evaluate("([s, c]) => window.__vp.setStatus(s, c)", list(shown_status))
                if pt is None:
                    if seen:
                        show_preview(seen, None, False)
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
                if seen:
                    show_preview(seen, pt, pinch.closed)
                # closing the pinch moves the fingertip, so select where it was pointing just before
                _, px, py = min(history, key=lambda h: abs(h[0] - (now - args.pinch_lookback)))
                for action, value in gesture.step(confirmed, pinch.closed, smoothed, (px, py), now):
                    if action == "select":
                        page.evaluate("([fx, fy]) => window.__vp.selectAt(fx * innerWidth, fy * innerHeight)", list(value))
                        shoot(value)
                    elif action == "click":
                        # select (sticky highlight) then send a real mouse click at the element's centre
                        c = page.evaluate("([fx, fy]) => window.__vp.selectAt(fx * innerWidth, fy * innerHeight)", list(value))
                        shoot(value)  # before the click: it may navigate away
                        if c:
                            page.mouse.click(c[0], c[1])
                    elif action in ("back", "forward"):
                        selection_store.clear_selection()
                        (page.go_back if action == "back" else page.go_forward)(timeout=10000)
                    elif action == "scroll_start":
                        page.mouse.move(float(value[0]), float(value[1]))  # wheel events go to what is under the mouse
                    elif action == "scroll":
                        page.mouse.wheel(0, float(value))
            if voice:
                voice.stop()
            browser.close()
    except Exception as e:  # camera/browser failures should end cleanly, not hang
        if "has been closed" in str(e):  # the window was closed (Esc/quit) mid-frame: a normal exit
            return 0
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        if log:
            log.close()
        selection_store.clear_screenshots()  # they can show private page content
        cv2.destroyAllWindows()
        cap.release()
        landmarker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
