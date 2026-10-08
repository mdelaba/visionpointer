# Architecture and original design

> This is the design written before the build. It describes the plan, and parts of it changed. Today: the pointer is the **thumb tip** (not the index fingertip); selection is pinch only (dwell is off by default) with a 50 px snap radius; and there is no built-in model router, because agents connect through the MCP server and fetch a screenshot only when a question needs one (see the README).

## Vision

### Core Concept
**VisionPointer** is an open, cross-platform interaction engine that enables users to point directly at physical or digital screens—using a standard laptop webcam, touchscreen display, or smart glasses—and receive real-time, context-aware visual and audio guidance from a Multimodal Large Language Model (MLLM).

### Problem Statement
Interacting with complex user interfaces (UIs), software tutorials, or physical dashboards often requires clumsy manual inputs (screenshots, cursor highlighting, text descriptions). While Multimodal LLMs excel at visual comprehension, they lack spatial awareness of physical gestures unless explicitly bridged by computer vision coordinate transformers.

### Solution
A lightweight, open agent that combines:
1. **Real-time spatial finger tracking** via standard camera feeds (MediaPipe / OpenCV) or native hardware API touch events.
2. **Homography calibration & DOM mapping** to convert imprecise gesture vectors into pixel-accurate screen target coordinates.
3. **Visual context injection** that auto-annotates screen captures with target overlays and element bounding boxes before routing the payload to MLLMs (e.g., GPT-4o, Claude 3.5 Sonnet, local vision models).

## System Architecture & Technical Stack

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

## Technical Implementation & Workflows

### Calibration Protocol (Webcam Setup)
1. **Interactive Prompt:** The UI displays four target crosshairs sequentially at screen corners $(0,0)$, $(W,0)$, $(W,H)$, and $(0,H)$.
2. **Gesture Sampling:** The user points at each target. The camera records 10-15 landmark frames of the thumb tip (`THUMB_TIP`).
3. **Homography Solver:** OpenCV calculates the perspective transform matrix $H$:
   $$\begin{bmatrix} x_{\text{screen}} \\ y_{\text{screen}} \\ 1 \end{bmatrix} = H \cdot \begin{bmatrix} x_{\text{camera}} \\ y_{\text{camera}} \\ 1 \end{bmatrix}$$
4. **Persisted Matrix:** $H$ is stored locally for active session tracking.

### Pointing-to-Prompt Execution Flow
1. **Trigger Event:** User performs a **Pinch Gesture** (thumb-to-index proximity) or holds a **Dwell Hover** over a screen region for 800ms.
2. **Coordinate Extraction:** The engine extracts $(x, y)$ coordinates and maps them via Matrix $H$.
3. **DOM Snapping:** The system fetches interactive DOM nodes within radius $R$ (default: 100px) and snaps the cursor to the nearest button/link element.
4. **Visual Annotation:** A red target crosshair and bounding highlight are rendered directly onto a high-res screenshot.
5. **Multimodal API Request:**
   * **System Prompt:** *"You are a real-time UI guidance assistant. The user is pointing at the marked red region on their screen. Explain what this element does and what step they should take next based on their request."*
   * **User Prompt:** *[Optional Voice Input or Default Guidance Prompt]*
   * **Payload:** Base64-encoded annotated image + snapped DOM metadata.
