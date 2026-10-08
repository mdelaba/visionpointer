# Agent Instructions

You are a coding agent assigned to build the **VisionPointer** project. 
The user has provided a `README.md` file detailing the core concept, architecture, and roadmap.

## Goal
Your current primary objective is to complete **Milestone 1: Proof-of-Concept (POC) Script** as defined in the README.

## Key Requirements for Milestone 1
- **Language**: Python
- **Libraries to Use**: `mediapipe` (for hand tracking), `opencv-python` (for webcam access and image processing), `mss` (for screen capture), `openai` (for the multimodal API).
- **Core Functionality**:
  1. Capture video feed from the built-in webcam.
  2. Use MediaPipe Hands to track the index finger tip (`INDEX_FINGER_TIP`).
  3. Recognize a gesture (e.g., a "pinch" or "dwell") as the trigger event.
  4. Capture the screen when the trigger event occurs.
  5. Annotate the screenshot with a visual marker (e.g., a red target crosshair) at the estimated pointing location.
  6. Encode the annotated image as base64 and send it to the OpenAI API (using `gpt-4o`) with a prompt asking for guidance about what is on the screen at that location.
  7. Output the response.

## Instructions
1. Familiarize yourself with the `README.md` context.
2. Set up the project structure in the `src/` directory.
3. You can utilize the provided `requirements.txt` to set up the python environment. Please use `uv` for python environments, per the user rules.
4. Build the core components step by step, ensuring you add timeout and error handling for external inputs like the webcam and API calls.
5. Create small, executable scripts to test webcam integration and screen capture independently before wiring everything together into the final pipeline.

Do not over-engineer at this stage. Focus on a standalone Python script to prove the concept.
