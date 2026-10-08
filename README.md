# VisionPointer: Comprehensive Project Plan & Architecture

---

## Getting Started

VisionPointer lets you point at a web page with your hand in front of a webcam, pinch your thumb and index finger to select an element, and hand that element to an AI agent through an MCP server.

### Requirements
* Linux with a webcam (developed on Arch + Hyprland; the browser runs under Wayland/XWayland)
* [uv](https://docs.astral.sh/uv/) and Python 3.11 (uv installs it if needed)
* Optional: Claude Code (or any MCP-capable agent) to consume the selection

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
`mediapipe` is pinned to 0.10.21 on purpose: 1.x crashed when creating the hand landmarker in testing.

### 2. Check hand tracking and pinch detection
```bash
./test
```
A blue circle follows your index fingertip in the webcam preview and turns green while you pinch. The top line shows the thumb-to-index ratio. Tune with `--pinch-close` (default 0.20) and `--pinch-open` (default 0.25). Press `q` or Esc to quit.

### 3. Calibrate
```bash
./calibrate --recalibrate
```
Point at each red crosshair and press SPACE (keep your finger visible and steady while it samples). This saves `calibration.json`, which is only valid for the same screen size and camera resolution, so recalibrate if either changes. Afterwards the script shows the circle on a fullscreen canvas so you can check the accuracy. Press `c` to recalibrate and `q` to quit.

### 4. Point at web elements
```bash
./web-pointer              # free pointing on the test page
./web-pointer --hit-test   # scored test, results printed as VP_HIT lines
./web-pointer --url https://example.com
```
Hold your hand in a hook posture (index finger curled near the thumb) and move your hand to move the circle. The nearest clickable element within 50 px gets a blue outline (this includes elements inside web components, and `div`/`span` buttons with a pointer cursor). If nothing clickable is close, the paragraph, heading, list item, table cell, image or caption directly under the circle gets the outline instead. Pinch and release to select it: it gets a sticky green highlight and is written to `~/.cache/visionpointer/selection.json`. Pinch and release on empty space to clear. To scroll, pinch and drag your hand up or down: once you move past a small threshold the circle turns orange and the page follows your hand like a touchscreen (hand up scrolls down). A scroll does not change the selection. Press Esc in the browser to quit. On Hyprland the script asks for fullscreen itself, because pointing only maps correctly when the page fills the screen.

Useful options: `--radius` (snap radius, px), `--dwell-ms` (also select after holding; 0 = off), `--smooth` / `--smooth-beta` (steadiness vs lag), `--scroll-threshold` (px of movement before a pinch becomes a scroll, default 40), `--scroll-gain` (scroll distance per px of hand movement, default 1.5), `--confidence`, `--max-jump`, `--timeout` (default 300 s), `--debug-log file.csv` (per-frame positions and pinch ratio for tuning).

(`./test`, `./calibrate` and `./web-pointer` are launchers for the scripts in `src/`; all flags pass through.)

### 5. Connect an agent (MCP)
```bash
claude mcp add visionpointer -- "$PWD/.venv/bin/python" "$PWD/src/mcp_server.py"
```
While `web_pointer.py` is running, select an element by pinching and ask the agent about "this". It calls `get_selected_element` (and `get_selection_history`) to see the selector, text, attributes, HTML snippet, bounding box, page URL/title, and how long ago it was selected. For other agents, register `src/mcp_server.py` as a stdio MCP server, or read the JSON state files directly. Set `VP_STATE_DIR` to change where they are stored.

### Troubleshooting
* **Circle only reaches part of the screen:** the browser isn't fullscreen. Make the window fullscreen.
* **"No calibration for this screen size and camera resolution":** run step 3 again.
* **Jittery pointer or jumps:** check lighting (the camera drops its frame rate in dim light), raise `--confidence`, or lower `--smooth`.
* **Camera not found:** try `--camera 1` (or check `ls /dev/video*`).

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
2. **Gesture Sampling:** The user points at each target. The camera records 10-15 landmark frames of the index fingertip (`INDEX_FINGER_TIP`).
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
             │   - MIT/Apache License                           │
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

VisionPointer only handles the pointing half of "voice + pointing". This section records the plan for the voice half. It is likely a separate companion project rather than part of this one, and nothing here is built yet.

### What exists today
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
