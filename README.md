# VisionPointer

Point at your screen with your hand and ask your AI about it. Webcam hand tracking, pinch to select, and an MCP server that gives Claude the selected element, with optional voice.


https://github.com/user-attachments/assets/339617e5-d584-4287-b0bf-3c75d8cf7eb0


---

## Getting Started

You hold your hand in front of a webcam and move a circle over a web page. Pinching your thumb and index finger selects the element under it, and the selection goes to an AI agent through an MCP server. You can also just ask the agent about it out loud (see Voice).

### Requirements
* Linux with a webcam (developed on Arch + Hyprland; the browser runs under Wayland/XWayland)
* [uv](https://docs.astral.sh/uv/) and Python 3.11 (uv installs it if needed)
* Optional: Claude Code (or any MCP-capable agent) to consume the selection
* Optional, for voice: [Claude Code](https://claude.com/claude-code) installed and signed in (voice runs `claude -p`), PipeWire (`pw-record` and `pw-play`), and a working microphone

### 1. Install
```bash
git clone https://github.com/mdelaba/visionpointer.git
cd visionpointer
uv venv -p 3.11 .venv
uv pip install -p .venv/bin/python -r requirements.txt
PLAYWRIGHT_BROWSERS_PATH=$PWD/.browsers .venv/bin/python -m playwright install chromium
mkdir -p models
curl -L -o models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
```
For voice (`--voice`), also download the speech voice (the Whisper model downloads itself on first use):
```bash
mkdir -p models/piper
.venv/bin/python -m piper.download_voices en_US-lessac-medium --download-dir models/piper
```
`mediapipe` is pinned to 0.10.21 on purpose: 1.x crashed when creating the hand landmarker in testing.

### 2. Check hand tracking and pinch detection
```bash
./test
```
A blue circle follows your thumb tip in the webcam preview and turns green while you pinch. The top line shows the thumb-to-index ratio. Tune with `--pinch-close` (default 0.18) and `--pinch-open` (default 0.23). Press `q` or Esc to quit.

### 3. Calibrate
```bash
./calibrate --recalibrate
```
Hold your hand at the distance and height you will normally use, with the camera in its final position (moving the camera or sitting much closer or farther later makes the pointer drift). Point at each red crosshair with your **thumb tip** (the circle follows the thumb tip, so calibrate with it) and press SPACE, keeping your hand visible and steady while it samples. This saves `calibration.json`, which is only valid for the same screen size and camera resolution, so recalibrate if either changes. Afterwards the script shows the circle on a fullscreen canvas so you can check the accuracy. Press `c` to recalibrate and `q` to quit.

### 4. Point at web elements
```bash
./web-pointer              # free pointing on the test page
./web-pointer --hit-test   # scored test, results printed as VP_HIT lines
./web-pointer --url https://example.com
```
Hold your hand with the index finger curled near the thumb and move your hand to move the circle. The circle sits on your thumb tip, which stays put while the index finger closes on it, so it does not jump when you pinch (calibrate with your thumb tip too). The nearest clickable element within 50 px gets a blue outline (this includes elements inside web components, and `div`/`span` buttons with a pointer cursor). If nothing clickable is close, the paragraph, heading, list item, table cell, image or caption directly under the circle gets the outline instead. Pinch and release to select it: it gets a sticky green highlight and is written to `~/.cache/visionpointer/selection.json`. Pinch and release on empty space to clear. To scroll, pinch and drag your hand up or down: once you move past a small threshold the circle turns orange and the page follows your hand like a touchscreen (hand up scrolls down). A scroll does not change the selection. To click, pinch and hold still for 0.6 s: the circle turns purple and a real mouse click is sent to the element. To go back or forward, pinch and drag your hand sideways (right = back, left = forward, like swiping a touchscreen). Press Esc in the browser to quit. On Hyprland the script asks for fullscreen itself, because pointing only maps correctly when the page fills the screen.

(`./test`, `./calibrate` and `./web-pointer` are launchers for the scripts in `src/`; all flags pass through.)

### 5. Voice quick-start (optional)
Needs Claude Code installed and signed in, the Piper voice from step 1, a microphone and PipeWire. You do not need to register the MCP server in step 6: voice gives its own `claude -p` calls just the VisionPointer tools.
```bash
./web-pointer --voice --screenshots --url https://en.wikipedia.org/wiki/Hand
```
Wait for "Voice ready" in the terminal (the first run downloads the Whisper model), then hold your hand in view, point at something, pinch-select it and just ask: "what is this?". The banner at the bottom of the page shows what it hears and says. It only listens while a hand is visible. Say "new conversation" to reset context. Speech is transcribed on your machine and spoken back locally, but the text of your question and the selected element are sent to Claude (and a screenshot too, if `--screenshots` is on and Claude asks for one). Use headphones if you record a demo, otherwise a microphone can pick up the spoken reply. Drop `--screenshots` if you do not want Claude to be able to see the page. More details in [docs/VOICE.md](docs/VOICE.md).

### 6. Connect an agent (MCP)
```bash
claude mcp add visionpointer -- "$PWD/.venv/bin/python" "$PWD/src/mcp_server.py"
```
While `web_pointer.py` is running, select an element by pinching and ask the agent about "this". It calls `get_selected_element` (and `get_selection_history`) to see the selector, text, attributes, HTML snippet, bounding box, page URL/title, and how long ago it was selected. For other agents, register `src/mcp_server.py` as a stdio MCP server, or read the JSON state files directly. Set `VP_STATE_DIR` to change where they are stored.

**Nothing selected.** If you ask while nothing is selected, `get_selected_element` returns the page you are on instead: URL, title, viewport, scroll position, page height and the first 3,000 characters of visible text. `get_selection_screenshot` then returns a screenshot of the whole current page (needs `--screenshots`). This works only while `web_pointer` is running; the screenshot is taken at the moment of the request.

**Screenshots (opt-in).** Start with `--screenshots` and each selection also saves a screenshot, so the agent can look at the page when a question needs it ("what does this picture show?", "where is that button?"). The agent asks for it through a separate MCP tool, `get_selection_screenshot(view)`, so text-only questions never pay for an image. Views: `annotated` (the visible page with a red box around the selected element and a crosshair where you pointed), `crop` (the element with a small margin) and `clean` (no marks). The result also gives the element box and pointer position in image pixels and as 0 to 1 fractions, the viewport size and the device pixel ratio. Images are scaled to at most 1568 px on the long side.

Privacy: screenshots can contain anything on the page, such as email or banking, and are sent to the model provider (Anthropic, if the agent is Claude) when the agent looks at one. That is why this is off by default. They are saved in `~/.cache/visionpointer/screenshots/` (three PNGs per selection, named by timestamp: `_annotated`, `_crop`, `_clean`), only the last 5 selections are kept, and they are deleted when the selection is cleared or the program exits.

### Recording a demo
`./web-pointer --preview` opens a small webcam window (320 px wide) showing your hand, a circle on the thumb tip (green while pinched) and a white dot on the index tip. It floats over the screen, so `wf-recorder` captures it along with the page. To pin it to a corner in Hyprland, add window rules for the title `VisionPointer`: `float`, `pin`, `size 320 180` and `move 100%-340 100%-200`. Start `web-pointer` first, then the recording, and make sure the pointer window is the focused one when it goes fullscreen.

### Flag reference (`./web-pointer`)
| Flag | Default | Meaning |
|---|---|---|
| `--url` | test page | page to open |
| `--camera` | 0 | camera index |
| `--timeout` | 300 | max run time, seconds |
| `--radius` / `--no-snap` | 50 | snap radius in px / only exact hits count |
| `--dwell-ms` | 0 | also select after holding this long (0 = off) |
| `--pinch-close` / `--pinch-open` | 0.18 / 0.23 | thumb-index ratio to start / end a pinch |
| `--pinch-lookback` | 0.25 | select where you pointed this many seconds ago |
| `--smooth` / `--smooth-beta` | 0.45 / 0.01 | steadiness vs lag |
| `--max-jump` | 300 | ignore single-frame jumps above this many px |
| `--confidence` | 0.8 | hand detection threshold |
| `--scroll-threshold` / `--scroll-gain` | 40 / 1.2 | px before a pinch scrolls / scroll per px of hand |
| `--swipe-threshold` | 250 | sideways px for back/forward (0 = off) |
| `--click-hold` | 0.6 | seconds to hold a pinch to click (0 = off) |
| `--voice` | off | talk to Claude, listening only while a hand is visible |
| `--voice-model` / `--voice-silence` | haiku / 0.8 | Claude model / seconds of silence that end a question |
| `--preview` | off | small mirrored webcam window with the tracked hand (for demo recordings) |
| `--screenshots` | off | save screenshots so Claude can see the page (privacy) |
| `--hit-test` / `--debug-log` | off | scored test page / per-frame CSV for tuning (positions and pinch ratio) |

### Troubleshooting
* **Circle only reaches part of the screen:** the browser isn't fullscreen. Make the window fullscreen.
* **"No calibration for this screen size and camera resolution":** run step 3 again.
* **Jittery pointer or jumps:** check lighting (the camera drops its frame rate in dim light), raise `--confidence` (hand detection threshold, default 0.8), or lower `--smooth`.
* **Camera not found:** try `--camera 1` (or check `ls /dev/video*`).
* **Voice does not hear you or hears noise:** check the default microphone with `wpctl status`; if its volume is low, raise it with `wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 0.6`. Fans and typing can trigger it, see [docs/VOICE.md](docs/VOICE.md) for how noise is handled.
* **"Voice unavailable" at startup:** the Piper voice or a package is missing; repeat the voice download in step 1 and `uv pip install -r requirements.txt`.
* **Voice answers feel slow:** the delay is mostly `claude -p` starting up (about 4 s). Shorten `--voice-silence` to end your question sooner, or keep the default `haiku` model.
* **Claude says nothing is selected or cannot see the page:** the pointer must be running (`web_pointer`), and screenshots need `--screenshots`.

---

## Use Cases

The same pointing, selecting, scrolling, clicking and back/forward gestures serve several kinds of users. All of the following work in the demo today, inside the VisionPointer browser window.

* **Pointing at things for an AI agent (developers and general users).** Point at a button, paragraph, image or error message, pinch to select it, and ask an agent "what does this do?" or "fix this". The agent receives the selector, text, attributes, HTML, position and page URL through MCP, so there is no screenshotting or describing the element in words.
* **Hands-free web navigation (accessibility).** For people who cannot comfortably use a mouse or keyboard: move the circle with your hand, snap onto links and buttons, pinch to select, pinch and drag to scroll, pinch-and-hold to click, swipe sideways for back/forward. Snapping to the nearest target makes small, shaky hand movements usable.
* **Presenting and demonstrating (meetings and demos).** Drive a web-based slide deck or demo from a screen without a mouse: point at an item to highlight it, scroll, with the audience seeing the circle and the highlighted element.
* **Web development and QA.** Use the selector and bounding box of a pinched element to tell an agent exactly which part of a page a bug report or change request is about.

Not covered yet: native (non-browser) apps, your everyday browser, and pointing from across a room. See [docs/ROADMAP.md](docs/ROADMAP.md).

---

## How it works
```
webcam -> MediaPipe hand landmarks -> thumb tip -> 4-point calibration -> screen position
  -> snap to the nearest element in a Playwright browser -> pinch to select
  -> selection + optional screenshot written to ~/.cache/visionpointer -> MCP server -> your agent
```
Voice (optional) adds a local microphone pipeline: speech to text on your machine, the question goes to `claude -p`, and the reply is spoken locally.

## Status

A working prototype, developed and tested on Linux (Arch + Hyprland). Calibration is per screen and camera, and the pointer works in its own Playwright browser window.

**Built so far**
* Hand tracking, 4-point calibration, smoothing and spike rejection.
* Snapping to interactive elements, with hysteresis; selection of text and media blocks; open shadow DOM; `div`/`span` buttons with a pointer cursor.
* Pinch-to-select, pinch-and-drag to scroll, pinch-and-hold to click, and pinch-and-swipe sideways for back/forward.
* The pointer circle follows the thumb tip, so it does not jump when you pinch. Pinch thresholds are 0.18 to close and 0.23 to open.
* Voice (`--voice`): hands-free questions about the pointed-at element, spoken answers, local speech models, resumed Claude session.
* MCP server with `get_selected_element`, `get_selection_history` and `get_selection_screenshot`; with nothing selected they return the current page's info and screenshot.
* Screenshots (`--screenshots`, opt-in): annotated page, element crop and clean page saved with each selection and fetched by the agent only when a question needs to see the page.

Planned work is in [docs/ROADMAP.md](docs/ROADMAP.md).

## More documentation
* [Voice](docs/VOICE.md): how the voice pipeline works, noise handling, and the wake-word plan
* [Architecture and original design](docs/ARCHITECTURE.md)
* [Roadmap](docs/ROADMAP.md)
* [Dedicated hardware ideas](docs/HARDWARE.md)

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
