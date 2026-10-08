# Dedicated hardware input devices

## Goal
Build and support purpose-made hardware that lets people work with AI without a keyboard and mouse. A finger tracked by a webcam is the zero-cost starting point, but it is limited by parallax, missing depth, and camera angle. Dedicated hardware should give much more accurate positioning, and it should plug into the same input layer as the webcam and touchscreen sources.

## Device Concepts
| Device | Role | Possible Approaches |
| :--- | :--- | :--- |
| **Pointer device** | Precise on-screen positioning and selection | Handheld or wearable pointer (ring, wand, stylus) tracked by IR LED/marker constellation and a camera, laser/IR-spot tracking, or IMU + absolute-position reference (similar to Wii-style IR bar). Trigger button or pinch sensor for "select". |
| **Navigation device** | Scrolling, tab/page navigation, back/forward | Separate hand-held or wearable controller: scroll wheel/ring, trackpoint or joystick, IMU tilt or gestures, a few programmable buttons. |
| **Combined setup** | Pointer in one hand, navigator in the other | Both devices report through the same protocol, so either can be used alone or together. |

## Design Principles
1. **Same pipeline:** every device is just another pointer source producing screen `(x, y)` and events (select, scroll, navigate) that feed the existing element-lookup and agent step. The webcam, touchscreen, and hardware devices all share one input abstraction (see ROADMAP.md).
2. **Accuracy first:** the target is pixel-level positioning without per-session calibration, so element snapping is a convenience and not a necessity.
3. **Agent-native events:** besides plain mouse-style events, devices can send richer intents (for example "this element, explain it", "scroll to the next section") for the AI agent to consume directly.
4. **Open and cross-platform:** open protocol (USB HID and/or BLE) plus open reference firmware and hardware designs, so others can build compatible devices.
5. **Low latency:** pointer events must feel instant, and the agent round trip should never block the pointing itself.

## Rough Plan
1. **Research:** compare tracking approaches (IR/marker tracking, IMU + reference, laser-spot) for accuracy, cost, and latency, and decide on the pointer and navigator form factors.
2. **Prototype:** build with off-the-shelf parts (microcontroller, IMU, IR LEDs, a cheap camera) and connect it through the existing input abstraction.
3. **Protocol:** define the device-to-host event protocol (HID/BLE) and a host driver in this project.
4. **Iterate:** user-test pointer accuracy and navigation ergonomics, then refine the hardware.
5. **Support:** document the build, publish firmware and designs, and decide whether to offer manufactured units.
