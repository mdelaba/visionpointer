# VisionPointer: Comprehensive Project Plan & Architecture

---

## Getting Started

VisionPointer lets you point at a web page with your hand in front of a webcam, pinch your thumb and index finger to select an element, and hand that element to an AI agent through an MCP server.

### Requirements
* Linux with a webcam (developed on Arch + Hyprland; the browser runs under Wayland/XWayland)
* [uv](https://docs.astral.sh/uv/) and Python 3.11 (uv installs it if needed)
* Optional: Claude Code (or any MCP-capable agent) to consume the selection
* Optional, for voice: PipeWire (`pw-record` and `pw-play`) and a working microphone

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

Useful options: `--radius` (snap radius, px), `--dwell-ms` (also select after holding; 0 = off), `--smooth` / `--smooth-beta` (steadiness vs lag), `--scroll-threshold` (px of movement before a pinch becomes a scroll, default 40), `--scroll-gain` (scroll distance per px of hand movement, default 1.2), `--swipe-threshold` (px of sideways movement for back/forward, default 250, 0 = off), `--click-hold` (seconds to hold a pinch still to click, default 0.6, 0 = off), `--confidence` (hand detection threshold, default 0.8), `--max-jump`, `--timeout` (default 300 s), `--debug-log file.csv` (per-frame positions and pinch ratio for tuning).

(`./test`, `./calibrate` and `./web-pointer` are launchers for the scripts in `src/`; all flags pass through.)

### 5. Voice quick-start (optional)
Needs the Piper voice from step 1, a microphone, PipeWire and the MCP server from step 6 registered.
```bash
./web-pointer --voice --screenshots --url https://en.wikipedia.org/wiki/Hand
```
Wait for "Voice ready" in the terminal (the first run downloads the Whisper model), then hold your hand in view, point at something, pinch-select it and just ask: "what is this?". The banner at the bottom of the page shows what it hears and says. It only listens while a hand is visible. Say "new conversation" to reset context. Drop `--screenshots` if you do not want Claude to be able to see the page. More details in Section 8.

### 6. Connect an agent (MCP)
```bash
claude mcp add visionpointer -- "$PWD/.venv/bin/python" "$PWD/src/mcp_server.py"
```
While `web_pointer.py` is running, select an element by pinching and ask the agent about "this". It calls `get_selected_element` (and `get_selection_history`) to see the selector, text, attributes, HTML snippet, bounding box, page URL/title, and how long ago it was selected. For other agents, register `src/mcp_server.py` as a stdio MCP server, or read the JSON state files directly. Set `VP_STATE_DIR` to change where they are stored.

**Nothing selected.** If you ask while nothing is selected, `get_selected_element` returns the page you are on instead: URL, title, viewport, scroll position, page height and the first 3,000 characters of visible text. `get_selection_screenshot` then returns a screenshot of the whole current page (needs `--screenshots`). This works only while `web_pointer` is running; the screenshot is taken at the moment of the request.

**Screenshots (opt-in).** Start with `--screenshots` and each selection also saves a screenshot, so the agent can look at the page when a question needs it ("what does this picture show?", "where is that button?"). The agent asks for it through a separate MCP tool, `get_selection_screenshot(view)`, so text-only questions never pay for an image. Views: `annotated` (the visible page with a red box around the selected element and a crosshair where you pointed), `crop` (the element with a small margin) and `clean` (no marks). The result also gives the element box and pointer position in image pixels and as 0 to 1 fractions, the viewport size and the device pixel ratio. Images are scaled to at most 1568 px on the long side.

Privacy: screenshots can contain anything on the page, such as email or banking, and are sent to Anthropic when the agent looks at one. That is why this is off by default. They are saved in `~/.cache/visionpointer/screenshots/` (three PNGs per selection, named by timestamp: `_annotated`, `_crop`, `_clean`), only the last 5 selections are kept, and they are deleted when the selection is cleared or the program exits.

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
| `--screenshots` | off | save screenshots so Claude can see the page (privacy) |
| `--hit-test` / `--debug-log` | off | scored test page / per-frame CSV |

### Troubleshooting
* **Circle only reaches part of the screen:** the browser isn't fullscreen. Make the window fullscreen.
* **"No calibration for this screen size and camera resolution":** run step 3 again.
* **Jittery pointer or jumps:** check lighting (the camera drops its frame rate in dim light), raise `--confidence` (hand detection threshold, default 0.8), or lower `--smooth`.
* **Camera not found:** try `--camera 1` (or check `ls /dev/video*`).

---

## Use Cases

The same pointing, selecting, scrolling, clicking and back/forward gestures serve several kinds of users. All of the following work in the demo today, inside the VisionPointer browser window.

* **Pointing at things for an AI agent (developers and general users).** Point at a button, paragraph, image or error message, pinch to select it, and ask an agent "what does this do?" or "fix this". The agent receives the selector, text, attributes, HTML, position and page URL through MCP, so there is no screenshotting or describing the element in words.
* **Hands-free web navigation (accessibility).** For people who cannot comfortably use a mouse or keyboard: move the circle with your hand, snap onto links and buttons, pinch to select, pinch and drag to scroll, pinch-and-hold to click, swipe sideways for back/forward. Snapping to the nearest target makes small, shaky hand movements usable.
* **Presenting and demonstrating (meetings and demos).** Drive a web-based slide deck or demo from a screen without a mouse: point at an item to highlight it, scroll, with the audience seeing the circle and the highlighted element.
* **Web development and QA.** Use the selector and bounding box of a pinched element to tell an agent exactly which part of a page a bug report or change request is about.

Not covered yet: native (non-browser) apps, your everyday browser, pointing from across a room, and voice. See Section 9 for the build work.

---

## 1. Executive Summary & Vision

### Core Concept
**VisionPointer** is an open, cross-platform interaction engine that enables users to point directly at physical or digital screens—using a standard laptop webcam, touchscreen display, or smart glasses—and receive real-time, context-aware visual and audio guidance from a Multimodal Large Language Model (MLLM).

### Problem Statement
Interacting with complex user interfaces (UIs), software tutorials, or physical dashboards often requires clumsy manual inputs (screenshots, cursor highlighting, text descriptions). While Multimodal LLMs excel at visual comprehension, they lack spatial awareness of physical gestures unless explicitly bridged by computer vision coordinate transformers.

### Solution
A lightweight, open-core agent that combines:
1. **Real-time spatial finger tracking** via standard camera feeds (MediaPipe / OpenCV) or native hardware API touch events.
2. **Homography calibration & DOM mapping** to convert imprecise gesture vectors into pixel-accurate screen target coordinates.
3. **Visual context injection** that auto-annotates screen captures with target overlays and element bounding boxes before routing the payload to MLLMs (e.g., GPT-4o, Claude 3.5 Sonnet, local vision models).

---

## 2. Target Platforms & Hardware Roadmap

The project follows a phased rollout across three primary hardware environments:

| Phase | Hardware Target | Interaction Method | Primary Challenges | Solution Approach |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1** | Standard Laptops & Webcams | In-air pointing gesture, pinch-to-select via built-in RGB webcam. | Parallax error, depth ambiguity ($Z$-axis), camera angle distortion. | 4-Corner Homography calibration, DOM bounding-box snapping, pinch-gesture trigger. |
| **Phase 2** | Touchscreen Laptops & Tablets | Physical display touch, capacitive digitizer, stylus. | Low latency requirement, palm rejection. | Native OS touch event listeners (`pointerdown`, `touchstart`), direct coordinate mapping. |
| **Phase 3** | Smart Glasses & Spatial Headsets | Egocentric camera stream, gaze vector + finger pointing in physical space. | Dynamic camera movement, environment lighting, real-world coordinate mapping. | Spatial depth estimation (ToF/Stereo), bounding-box object detection, head-pose tracking. |

---

## 3. System Architecture & Technical Stack

```text
                 +-------------------------------------------------------+
                 |                    INPUT LAYER                        |
                 |  Webcam Feed / Touch Events / Smart Glasses Stream    |
                 +---------------------------+---------------------------+
                                             |
                                             v
                 +-------------------------------------------------------+
                 |              COMPUTER VISION ENGINE                   |
                 |  - MediaPipe Hands (3D Landmarks)                     |
                 |  - Gesture Recognition (Pinch / Hover / Dwell)         |
                 |  - Homography / Perspective Transformer Matrix        |
                 +---------------------------+---------------------------+
                                             |
                                             v
                 +-------------------------------------------------------+
                 |             CONTEXT & SCREEN CAPTURE ENGINE           |
                 |  - Native Screen Capture / Window Stream               |
                 |  - DOM Bounding Box Extractor (Playwright/Extension)  |
                 |  - Coordinate Snap Engine (Nearest Interactive Node)  |
                 |  - Screen Annotation / Target Marker Overlay         |
                 +---------------------------+---------------------------+
                                             |
                                             v
                 +-------------------------------------------------------+
                 |                MULTIMODAL AI PIPELINE                 |
                 |  - Payload Builder (Annotated Screenshot + DOM JSON)  |
                 |  - MLLM Router (OpenAI GPT-4o, Claude, Ollama/Local) |
                 |  - Response Synthesizer (Text-to-Speech / UI Overlay) |
                 +-------------------------------------------------------+
```

### Stack Components

* **Gesture Tracking:** Python / JavaScript, Google MediaPipe Hands, OpenCV (`cv2.findHomography`).
* **Screen & DOM Parser:** Chrome Extension API / Playwright / Python `mss` screen grabber.
* **Backend Runtime:** Python (FastAPI / WebSockets) or Node.js / Electron.
* **LLM Engine:** OpenAI API (`gpt-4o`), Anthropic API (`claude-3-5-sonnet`), Google Gemini API (`gemini-1.5-pro`), or Local Vision Models (`ollama` / `llama-3.2-vision`).

---

## 4. Technical Implementation & Workflows

### 4.1 Calibration Protocol (Webcam Setup)
1. **Interactive Prompt:** The UI displays four target crosshairs sequentially at screen corners $(0,0)$, $(W,0)$, $(W,H)$, and $(0,H)$.
2. **Gesture Sampling:** The user points at each target. The camera records 10-15 landmark frames of the thumb tip (`THUMB_TIP`).
3. **Homography Solver:** OpenCV calculates the perspective transform matrix $H$:
   $$\begin{bmatrix} x_{\text{screen}} \\ y_{\text{screen}} \\ 1 \end{bmatrix} = H \cdot \begin{bmatrix} x_{\text{camera}} \\ y_{\text{camera}} \\ 1 \end{bmatrix}$$
4. **Persisted Matrix:** $H$ is stored locally for active session tracking.

### 4.2 Pointing-to-Prompt Execution Flow
1. **Trigger Event:** User performs a **Pinch Gesture** (thumb-to-index proximity) or holds a **Dwell Hover** over a screen region for 800ms.
2. **Coordinate Extraction:** The engine extracts $(x, y)$ coordinates and maps them via Matrix $H$.
3. **DOM Snapping:** The system fetches interactive DOM nodes within radius $R$ (default: 100px) and snaps the cursor to the nearest button/link element.
4. **Visual Annotation:** A red target crosshair and bounding highlight are rendered directly onto a high-res screenshot.
5. **Multimodal API Request:**
   * **System Prompt:** *"You are a real-time UI guidance assistant. The user is pointing at the marked red region on their screen. Explain what this element does and what step they should take next based on their request."*
   * **User Prompt:** *[Optional Voice Input or Default Guidance Prompt]*
   * **Payload:** Base64-encoded annotated image + snapped DOM metadata.

---

## 5. Go-to-Market & Monetization Strategy

### Model: Open-Core / Developer-First Ecosystem

```text
             ┌──────────────────────────────────────────────────┐
             │       OPEN SOURCE CORE ENGINE (GitHub)           │
             │   - Apache License 2.0                           │
             │   - Python/JS Gesture Tracking Engine            │
             │   - Homography Calibration Tool                  │
             │   - Basic CLI / Browser Extension                │
             └────────────────────────┬─────────────────────────┘
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
┌───────────────────────────────┐               ┌───────────────────────────────┐
│     COMMERCIAL B2C PRODUCT    │               │    ENTERPRISE / B2B SDK       │
│      (Freemium Desktop App)   │               │     (Glasses & Spatial AR)    │
│                               │               │                               │
│ • Free: BYO API Keys          │               │ • Smart Glasses SDK Licensing │
│ • Pro ($12-$20/mo):           │               │ • Enterprise Kiosk/A11y Setup │
│   - Managed Zero-Config APIs  │               │ • Custom On-Prem AI Routing   │
│   - Low-latency Voice Output  │               │ • Dedicated SLA & Security    │
│   - Local LLM Orchestration   │               │                               │
└───────────────────────────────┘               └───────────────────────────────┘
```

### Community & Growth Drivers
1. **GitHub Star & Demo Strategy:** Release a viral 30-second demo showing a user pointing at a complex spreadsheet or software interface with a standard webcam and receiving instant audio guidance.
2. **Accessibility Niche:** Position the core engine as a fundamental tool for assistive technology, enabling motor-impaired users to navigate screens using air gestures.
3. **Spatial Computing Bridge:** Engage hardware developers building smart glasses (e.g., Meta Ray-Ban, Apple Vision Pro, XREAL) who require gesture-to-LLM interfaces.

---

## 6. Immediate Next Steps / Roadmap

1. **Milestone 1: Proof-of-Concept (POC) Script**
   * Write a standalone Python script using `mediapipe`, `opencv-python`, and `openai`.
   * Implement screen capture, index finger tracking, and automatic GPT-4o screenshot payload submission.
2. **Milestone 2: Calibration & Snapping Layer**
   * Implement 4-point interactive screen homography matrix calculation.
   * Add a DOM snapping layer using Playwright or a Chrome Extension content script.
3. **Milestone 3: Touchscreen & Hybrid Input Integration**
   * Abstract the input layer to handle native OS touch inputs alongside webcam spatial vectors seamlessly.
4. **Milestone 4: Public GitHub Launch**
   * Package repository with clear setup instructions, demo video, and Apache 2.0 open-source licensing.
5. **Milestone 5 (Long-Term): Dedicated Pointing Hardware** — see Section 7.

---

## 7. Long-Term Vision: Dedicated Hardware Input Devices

### Goal
Build and support purpose-made hardware that lets people work with AI without a keyboard and mouse. A finger tracked by a webcam is the zero-cost starting point, but it is limited by parallax, missing depth, and camera angle. Dedicated hardware should give much more accurate positioning, and it should plug into the same input layer as the webcam and touchscreen sources.

### Device Concepts
| Device | Role | Possible Approaches |
| :--- | :--- | :--- |
| **Pointer device** | Precise on-screen positioning and selection | Handheld or wearable pointer (ring, wand, stylus) tracked by IR LED/marker constellation and a camera, laser/IR-spot tracking, or IMU + absolute-position reference (similar to Wii-style IR bar). Trigger button or pinch sensor for "select". |
| **Navigation device** | Scrolling, tab/page navigation, back/forward | Separate hand-held or wearable controller: scroll wheel/ring, trackpoint or joystick, IMU tilt or gestures, a few programmable buttons. |
| **Combined setup** | Pointer in one hand, navigator in the other | Both devices report through the same protocol, so either can be used alone or together. |

### Design Principles
1. **Same pipeline:** every device is just another pointer source producing screen `(x, y)` and events (select, scroll, navigate) that feed the existing element-lookup and agent step. The webcam, touchscreen, and hardware devices all share one input abstraction (Milestone 3).
2. **Accuracy first:** the target is pixel-level positioning without per-session calibration, so element snapping is a convenience and not a necessity.
3. **Agent-native events:** besides plain mouse-style events, devices can send richer intents (for example "this element, explain it", "scroll to the next section") for the AI agent to consume directly.
4. **Open and cross-platform:** open protocol (USB HID and/or BLE) plus open reference firmware and hardware designs, so others can build compatible devices.
5. **Low latency:** pointer events must feel instant, and the agent round trip should never block the pointing itself.

### Rough Plan
1. **Research:** compare tracking approaches (IR/marker tracking, IMU + reference, laser-spot) for accuracy, cost, and latency, and decide on the pointer and navigator form factors.
2. **Prototype:** build with off-the-shelf parts (microcontroller, IMU, IR LEDs, a cheap camera) and connect it through the existing input abstraction.
3. **Protocol:** define the device-to-host event protocol (HID/BLE) and a host driver in this project.
4. **Iterate:** user-test pointer accuracy and navigation ergonomics, then refine the hardware.
5. **Support:** document the build, publish firmware and designs, and decide whether to offer manufactured units.

---

## 8. Future Work: Hands-Free Voice Commands

VisionPointer only handles the pointing half of "voice + pointing". This section records the plan for the voice half. A first version is now built into `web-pointer` (see "What is built"); the wake word and tmux options below are still plans.

### What is built
`web-pointer --voice` talks to Claude about what you are pointing at, with no keyboard and no terminal:

```
mic (PipeWire default) -> only while a hand is visible -> record until 0.8 s of silence -> faster-whisper (local)
  -> claude -p --resume <stored session> (reads the pointed-at element via the visionpointer MCP) -> Piper (local) -> speakers
```

* Noise handling: the strictest voice-activity setting, 8 of the last 10 frames must be speech to start, an utterance needs about 0.45 s of speech, Whisper's own Silero filter drops non-speech, and low-confidence or repetitive transcripts are discarded. A rule that required speech to be louder than the room noise was tried and removed because it also blocked quiet speech. If your microphone volume is very low, raise it with `wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 0.6`.
* Listens only while a hand is detected (1 s grace); the microphone process is closed when no hand is in view and while Claude thinks and speaks, so it never hears its own voice.
* Only text goes to Claude. Audio is transcribed and spoken on this machine.
* Context carries over: the session id is stored in `~/.cache/visionpointer/voice/session_id` and resumed on each question. Say "new conversation" (or "start over") to reset it.
* Claude is limited to the read-only visionpointer tools (including the opt-in screenshot tool, see Section 4 step 6), and the call loads only the visionpointer MCP server (your other MCP servers would add seconds per question). Each `claude -p` call has a 90 s timeout.
* Models: `models/whisper` (base.en, about 140 MB, downloaded on first use) and `models/piper` (about 60 MB, see install). The status and last exchange show at the bottom of the page.
* Options: `--voice`, `--voice-model` (default `haiku` for speed; try `sonnet` for deeper answers), `--voice-silence` (seconds of silence that end a question).
* If it feels slow: shorten `--voice-silence`. Startup of `claude -p` is the main delay (about 4 s before the first sentence in testing); the model itself takes under 2 s with haiku. A long-lived Claude process would remove the startup cost.

### What existed before
* Claude Code's `/voice` is cloud speech-to-text: audio is streamed to Anthropic's servers and needs a claude.ai sign-in. Only the microphone capture is local.
* It needs a keypress to start, so there is no wake word and it is not hands-free.
* Dictation can auto-send without pressing Enter: `/voice tap` (tap to start, tap to send), or `"autoSubmit": true` in the `voice` settings object for hold mode. Both only submit transcripts of three words or more.

### Goal
Fully hands-free: say a wake word, speak a request ("what does this do?"), and have it sent to the agent while the pinch-selected element is the "this". No keyboard.

### Proposed design
A small local voice daemon that runs alongside `web-pointer`:

```
mic -> wake word -> record until silence -> speech-to-text -> send to the agent -> (optional) spoken reply
```

| Stage | Choice | Why |
| :--- | :--- | :--- |
| Wake word | openWakeWord (for example "hey claude") | Local, always listening, nothing leaves the machine |
| End of speech | Silero VAD | Stops recording when the user stops talking |
| Speech-to-text | faster-whisper (`base` or `small`) | Local, free, fast enough on CPU, works with any agent |
| Spoken reply (optional) | Piper TTS | The user is not looking at the terminal |
| Feedback | Short beeps on wake and on send | The user needs to know it heard them while pointing |

### How the text reaches the agent
1. **tmux (preferred):** the agent runs in a tmux pane and the daemon types the transcript with `tmux send-keys -l "<text>"` then `Enter`. This keeps the interactive session and works with any terminal agent.
2. **Headless:** run `claude -p "<text>" --continue` per utterance and read the reply back. Simple, but no interactive UI.
3. **Typing into the focused window** (`wtype`/`ydotool`): rejected, it breaks whenever focus changes.

The sender should be a pluggable command, with tmux as the default.

### Open issues
* **Permission prompts stall a hands-free session.** Allow-list `mcp__visionpointer__*` in the agent's settings; other tools need voice approval or an allow-list.
* **Echo:** TTS replies can trigger the wake word, so pause listening while speaking.
* **Interim option:** `/voice tap` with `autoSubmit` is the cheapest stopgap if a keypress is acceptable. It could be bound to a foot pedal or a button on the pointer hardware from Section 7.

---

## 9. Build Work

Everything still to build, roughly in priority order. "Done" items are listed so the history is in one place.

### Done
* Hand tracking, 4-point calibration, smoothing and spike rejection.
* Snapping to interactive elements, with hysteresis; selection of text and media blocks; open shadow DOM; `div`/`span` buttons with a pointer cursor.
* Pinch-to-select, pinch-and-drag to scroll, pinch-and-hold to click, and pinch-and-swipe sideways for back/forward.
* The pointer circle follows the thumb tip, so it does not jump when you pinch. Pinch thresholds are 0.18 to close and 0.23 to open.
* Voice (`--voice`): hands-free questions about the pointed-at element, spoken answers, local speech models, resumed Claude session.
* MCP server with `get_selected_element`, `get_selection_history` and `get_selection_screenshot`; with nothing selected they return the current page's info and screenshot.
* Screenshots (`--screenshots`, opt-in): annotated page, element crop and clean page saved with each selection and fetched by the agent only when a question needs to see the page.

### Next
1. **Work in the user's own browser.** Today the pointer only works in the Playwright kiosk window. Options: a browser extension (content script plus a local connection to the hand tracker), or the browser's accessibility tree.
2. **Native apps.** Use the OS accessibility tree (AT-SPI on Linux, UI Automation on Windows, AX on macOS) to snap to and describe elements outside the browser.
3. **Iframes.** Cross-origin iframes are invisible to the injected script; selection and clicking inside them do not work yet.
4. **Text-range selection.** Select a sentence or a span of words, not just a whole paragraph.
5. **Selection across page navigation.** Keep or clear the selection sensibly after a click changes the page.
6. **Tab switching gestures.** Back/forward (pinch-and-swipe sideways) is done; switching tabs was never started.
7. **Pointing from a distance.** Presenters stand away from the screen, so the camera-to-screen mapping needs a different approach (a wider camera view, or pointing direction instead of fingertip position).
8. **Touchscreen input source** alongside the webcam, using the same selection and MCP layer.
9. **Hands-free voice** (Section 8), including a wake word and sending the request to the agent.
10. **Page-scan throttling.** The element scan runs every 200 ms; throttle it if very long pages stutter.
11. **Packaging and public launch** (demo video, install instructions, licence; see Milestone 4).
12. **Dedicated pointing hardware** (Section 7).

### Future: Circle to Search
Similar to Google's Circle to Search: the user draws a loop around any part of the screen (text, an image, a chart, a region of an app) and the content inside it goes to an agent.

* **Gesture:** needs its own mode, because pinch-and-drag already scrolls. Candidates: a voice command ("circle"), a different pinch (middle finger and thumb), or a toggle with a held gesture. The circle turns a distinct colour while drawing, and a trail shows the path.
* **Capture:** take the bounding box of the path (or the path itself as a mask), then collect (a) a cropped screenshot of that region, (b) the DOM elements and text that fall inside it, and (c) the page URL and title.
* **Hand-off:** extend the MCP server with a `get_circled_region` tool returning the screenshot, text and elements, plus an entry in the selection history. The agent then answers questions about "this part" without the user describing it.
* **Beyond the browser:** with the native-app work above, the same gesture can capture any screen region through a screenshot. Searching the web for the circled content is just one thing an agent can do with it.
* **Open questions:** how to tell a deliberate loop from a normal hand movement (closure and size thresholds), and how to handle regions that cross iframes.

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
