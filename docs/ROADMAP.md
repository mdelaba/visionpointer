# Roadmap

What is built is listed in the README. This page is what is planned.

## Target Platforms & Hardware Roadmap

The project follows a phased rollout across three primary hardware environments:

| Phase | Hardware Target | Interaction Method | Primary Challenges | Solution Approach |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1** | Standard Laptops & Webcams | In-air pointing gesture, pinch-to-select via built-in RGB webcam. | Parallax error, depth ambiguity ($Z$-axis), camera angle distortion. | 4-Corner Homography calibration, DOM bounding-box snapping, pinch-gesture trigger. |
| **Phase 2** | Touchscreen Laptops & Tablets | Physical display touch, capacitive digitizer, stylus. | Low latency requirement, palm rejection. | Native OS touch event listeners (`pointerdown`, `touchstart`), direct coordinate mapping. |
| **Phase 3** | Smart Glasses & Spatial Headsets | Egocentric camera stream, gaze vector + finger pointing in physical space. | Dynamic camera movement, environment lighting, real-world coordinate mapping. | Spatial depth estimation (ToF/Stereo), bounding-box object detection, head-pose tracking. |

## Original milestones

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
5. **Milestone 5 (Long-Term): Dedicated Pointing Hardware** — see [HARDWARE.md](HARDWARE.md).

## Next
1. **Work in the user's own browser.** Today the pointer only works in the Playwright kiosk window. Options: a browser extension (content script plus a local connection to the hand tracker), or the browser's accessibility tree.
2. **Native apps.** Use the OS accessibility tree (AT-SPI on Linux, UI Automation on Windows, AX on macOS) to snap to and describe elements outside the browser.
3. **Iframes.** Cross-origin iframes are invisible to the injected script; selection and clicking inside them do not work yet.
4. **Text-range selection.** Select a sentence or a span of words, not just a whole paragraph.
5. **Selection across page navigation.** Keep or clear the selection sensibly after a click changes the page.
6. **Tab switching gestures.** Back/forward (pinch-and-swipe sideways) is done; switching tabs was never started.
7. **Pointing from a distance.** Presenters stand away from the screen, so the camera-to-screen mapping needs a different approach (a wider camera view, or pointing direction instead of fingertip position).
8. **Touchscreen input source** alongside the webcam, using the same selection and MCP layer.
9. **Hands-free voice** (see [VOICE.md](VOICE.md)), including a wake word and sending the request to the agent.
10. **Page-scan throttling.** The element scan runs every 200 ms; throttle it if very long pages stutter.
11. **Packaging and public launch** (demo video, install instructions, licence; launch is done).
12. **Dedicated pointing hardware** (see [HARDWARE.md](HARDWARE.md)).

## Future: Circle to Search
Similar to Google's Circle to Search: the user draws a loop around any part of the screen (text, an image, a chart, a region of an app) and the content inside it goes to an agent.

* **Gesture:** needs its own mode, because pinch-and-drag already scrolls. Candidates: a voice command ("circle"), a different pinch (middle finger and thumb), or a toggle with a held gesture. The circle turns a distinct colour while drawing, and a trail shows the path.
* **Capture:** take the bounding box of the path (or the path itself as a mask), then collect (a) a cropped screenshot of that region, (b) the DOM elements and text that fall inside it, and (c) the page URL and title.
* **Hand-off:** extend the MCP server with a `get_circled_region` tool returning the screenshot, text and elements, plus an entry in the selection history. The agent then answers questions about "this part" without the user describing it.
* **Beyond the browser:** with the native-app work above, the same gesture can capture any screen region through a screenshot. Searching the web for the circled content is just one thing an agent can do with it.
* **Open questions:** how to tell a deliberate loop from a normal hand movement (closure and size thresholds), and how to handle regions that cross iframes.
