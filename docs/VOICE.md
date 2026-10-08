# Voice

VisionPointer only handles the pointing half of "voice + pointing". This section records the voice half. A first version is now built into `web-pointer` (see "What is built"); the wake word and tmux options below are still plans.

## What is built
`web-pointer --voice` talks to Claude about what you are pointing at, with no keyboard and no terminal:

```
mic (PipeWire default) -> only while a hand is visible -> record until 0.8 s of silence -> faster-whisper (local)
  -> claude -p --resume <stored session> (reads the pointed-at element via the visionpointer MCP) -> Piper (local) -> speakers
```

* Noise handling: the strictest voice-activity setting, 8 of the last 10 frames must be speech to start, an utterance needs about 0.45 s of speech, Whisper's own Silero filter drops non-speech, and low-confidence or repetitive transcripts are discarded. A rule that required speech to be louder than the room noise was tried and removed because it also blocked quiet speech. If your microphone volume is very low, raise it with `wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 0.6`.
* Listens only while a hand is detected (1 s grace); the microphone process is closed when no hand is in view and while Claude thinks and speaks, so it never hears its own voice.
* Only text goes to Claude. Audio is transcribed and spoken on this machine.
* Context carries over: the session id is stored in `~/.cache/visionpointer/voice/session_id` and resumed on each question. Say "new conversation" (or "start over") to reset it.
* Claude is limited to the read-only visionpointer tools (including the opt-in screenshot tool, see the README's MCP section), and the call loads only the visionpointer MCP server (your other MCP servers would add seconds per question). Each `claude -p` call has a 90 s timeout.
* Models: `models/whisper` (base.en, about 140 MB, downloaded on first use) and `models/piper` (about 60 MB, see install). The status and last exchange show at the bottom of the page.
* Options: `--voice`, `--voice-model` (default `haiku` for speed; try `sonnet` for deeper answers), `--voice-silence` (seconds of silence that end a question).
* If it feels slow: shorten `--voice-silence`. Startup of `claude -p` is the main delay (about 4 s before the first sentence in testing); the model itself takes under 2 s with haiku. A long-lived Claude process would remove the startup cost.

## What existed before
* Claude Code's `/voice` is cloud speech-to-text: audio is streamed to Anthropic's servers and needs a claude.ai sign-in. Only the microphone capture is local.
* It needs a keypress to start, so there is no wake word and it is not hands-free.
* Dictation can auto-send without pressing Enter: `/voice tap` (tap to start, tap to send), or `"autoSubmit": true` in the `voice` settings object for hold mode. Both only submit transcripts of three words or more.

## Goal
Fully hands-free: say a wake word, speak a request ("what does this do?"), and have it sent to the agent while the pinch-selected element is the "this". No keyboard.

## Proposed design
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

## How the text reaches the agent
1. **tmux (preferred):** the agent runs in a tmux pane and the daemon types the transcript with `tmux send-keys -l "<text>"` then `Enter`. This keeps the interactive session and works with any terminal agent.
2. **Headless:** run `claude -p "<text>" --continue` per utterance and read the reply back. Simple, but no interactive UI.
3. **Typing into the focused window** (`wtype`/`ydotool`): rejected, it breaks whenever focus changes.

The sender should be a pluggable command, with tmux as the default.

## Open issues
* **Permission prompts stall a hands-free session.** Allow-list `mcp__visionpointer__*` in the agent's settings; other tools need voice approval or an allow-list.
* **Echo:** TTS replies can trigger the wake word, so pause listening while speaking.
* **Interim option:** `/voice tap` with `autoSubmit` is the cheapest stopgap if a keypress is acceptable. It could be bound to a foot pedal or a button on the pointer hardware from HARDWARE.md.
