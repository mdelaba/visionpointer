"""Talk to Claude about what you are pointing at, hands-free.

Listens (PipeWire default mic) only while a hand is detected, ends an utterance on silence, transcribes
it locally (faster-whisper), asks `claude -p` (resuming one stored session so context carries over;
Claude reads the pointed-at element through the visionpointer MCP) and speaks the reply locally (Piper)
through the PipeWire default output. Only text is sent to Claude; audio never leaves the machine.
"""
import collections
import json
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WHISPER_DIR = ROOT / "models" / "whisper"
PIPER_VOICE = ROOT / "models" / "piper" / "en_US-lessac-medium.onnx"
STATE_DIR = Path.home() / ".cache" / "visionpointer" / "voice"  # claude -p runs here: its sessions stay separate
SESSION_FILE = STATE_DIR / "session_id"
MCP_CONFIG = STATE_DIR / "mcp.json"  # only the visionpointer server: connecting all of your MCPs adds seconds per question

RATE = 16000
FRAME_MS = 30
FRAME_BYTES = RATE * FRAME_MS // 1000 * 2  # s16 mono
TOOLS = "mcp__visionpointer__get_selected_element,mcp__visionpointer__get_selection_history,mcp__visionpointer__get_selection_screenshot"
SYSTEM_PROMPT = (
    "You are answering by voice through VisionPointer. The user is pointing at their screen: when they say "
    "'this', 'that', 'here' or ask about something on screen, call get_selected_element to see it. "
    "Reply in one to three short, plain spoken sentences. No markdown, lists, code blocks or URLs. Do not narrate tool use; just answer. Call get_selection_screenshot only when the question needs to see the page (what a picture or chart shows, colours, layout, where something is); text questions never need it."
)
RESET_PHRASES = {"new conversation", "start over", "start a new conversation", "forget that", "reset"}
START_FRAMES = 8  # of the last 10 frames (300 ms) must be speech to start recording: single key clicks are too short
MIN_SPEECH_FRAMES = 15  # an utterance needs at least ~0.45 s of speech frames
NOISE = {"you", "thank you", "thanks for watching", "bye", "the"}  # typical Whisper hallucinations on silence


class VoiceAssistant:
    def __init__(self, model=None, silence_s=0.8, hand_grace_s=1.0, claude_timeout=90):
        self.model, self.silence_s, self.hand_grace_s, self.claude_timeout = model, silence_s, hand_grace_s, claude_timeout
        self.status, self.caption = "starting", ""
        self._hand_t = -1e9
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._mic = None

    # called from the main loop every frame
    def hand_seen(self):
        self._hand_t = time.monotonic()

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._kill_mic()
        self._thread.join(timeout=5)

    def _hand_present(self):
        return time.monotonic() - self._hand_t < self.hand_grace_s

    # ---- microphone -------------------------------------------------------------------------
    def _open_mic(self):
        self._mic = subprocess.Popen(
            ["pw-record", "--container", "raw", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

    def _kill_mic(self):
        if self._mic:
            self._mic.kill()
            self._mic.wait(timeout=2)
            self._mic = None

    def _frame(self):
        data = self._mic.stdout.read(FRAME_BYTES)
        return data if len(data) == FRAME_BYTES else None

    # ---- main loop --------------------------------------------------------------------------
    def _run(self):
        try:
            import webrtcvad
            from faster_whisper import WhisperModel
            from piper import PiperVoice

            self.status = "loading models"
            self._whisper = WhisperModel("base.en", device="cpu", compute_type="int8", download_root=str(WHISPER_DIR))
            self._piper = PiperVoice.load(str(PIPER_VOICE))
            vad = webrtcvad.Vad(3)  # strictest: steady noise such as fans is not speech
        except Exception as e:  # missing models/packages: report once and give up on voice
            self.status, self.caption = "voice off", f"voice unavailable: {e}"
            print(f"Voice unavailable: {e}", flush=True)
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        print("Voice ready: speak while your hand is in view.", flush=True)
        while not self._stop.is_set():
            if not self._hand_present():
                self._kill_mic()
                self.status = "idle (no hand)"
                time.sleep(0.1)
                continue
            if self._mic is None:
                self._open_mic()
            audio = self._listen(vad)
            if audio is None:
                continue
            self._kill_mic()  # nothing is recorded while Claude thinks and speaks
            try:
                self._handle(audio)
            except Exception as e:
                print(f"Voice error: {e}", flush=True)
                self.status = "error"

    def _listen(self, vad):
        """Block until one utterance has been captured; returns int16 samples, or None (hand gone / stopping)."""
        self.status = "listening"
        ring = collections.deque(maxlen=10)  # last 300 ms: (frame, is_speech)
        voiced, silent, speaking, speech_frames = [], 0, False, 0
        start = last_speech = time.monotonic()
        while not self._stop.is_set():
            if not speaking and not self._hand_present():
                return None
            frame = self._frame()
            if frame is None:
                return None
            is_speech = vad.is_speech(frame, RATE)
            if not speaking:
                ring.append((frame, is_speech))
                if sum(s for _, s in ring) >= START_FRAMES:
                    speaking, voiced, start = True, [f for f, _ in ring], time.monotonic()
                    speech_frames = sum(s for _, s in ring)
                    self.status = "hearing you"
            else:
                voiced.append(frame)
                speech_frames += is_speech
                if is_speech:
                    last_speech = time.monotonic()
                silent = 0 if is_speech else silent + 1
                if silent * FRAME_MS / 1000 >= self.silence_s or time.monotonic() - start > 30:
                    if speech_frames < MIN_SPEECH_FRAMES:  # a burst of noise, not words
                        speaking, voiced, silent, speech_frames = False, [], 0, 0
                        ring.clear()
                        self.status = "listening"
                        continue
                    self._timing = {"speech_s": last_speech - start, "end_wait_s": time.monotonic() - last_speech, "ended": time.monotonic()}
                    return np.frombuffer(b"".join(voiced), np.int16)
        return None

    # ---- one exchange -----------------------------------------------------------------------
    def _handle(self, audio):
        if len(audio) < RATE * 0.4:
            return
        self.status = "transcribing"
        segments, _ = self._whisper.transcribe(
            audio.astype(np.float32) / 32768, language="en", beam_size=1, condition_on_previous_text=False,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},  # Silero: drops non-speech before Whisper sees it
        )
        segments = list(segments)
        t = getattr(self, "_timing", None)
        if t:
            print(f"VOICE timing: spoke {t['speech_s']:.1f}s, waited {t['end_wait_s']:.2f}s after your last word to decide you were done, transcribed in {time.monotonic() - t['ended']:.2f}s", flush=True)
        if not segments:
            return
        text = " ".join(s.text.strip() for s in segments).strip()
        # low confidence or repetitive output is how Whisper hallucinates on noise
        if (not text or np.mean([s.no_speech_prob for s in segments]) > 0.5
                or np.mean([s.avg_logprob for s in segments]) < -1.0 or max(s.compression_ratio for s in segments) > 2.4
                or re.sub(r"[^a-z ]", "", text.lower()).strip() in NOISE):
            return
        print(f"VOICE heard: {text}", flush=True)
        self.caption = self._question = f"You: {text}"
        if re.sub(r"[^a-z ]", "", text.lower()).strip() in RESET_PHRASES:
            SESSION_FILE.unlink(missing_ok=True)
            say, finish = self._start_speaker()
            say("Okay, starting fresh.")
            finish()
            return
        self.status = "thinking"
        say, finish = self._start_speaker()
        try:
            reply = self._ask(text, say)
        finally:
            finish()  # waits until everything queued has been spoken
        print(f"\nVOICE reply: {reply}", flush=True)
        self.caption = f"You: {text}\nClaude: {reply}"

    def _ask(self, text, say):
        """Run claude -p, streaming: each finished sentence goes to say() while the rest is still being written."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        MCP_CONFIG.write_text(json.dumps({"mcpServers": {"visionpointer": {
            "command": sys.executable, "args": [str(ROOT / "src" / "mcp_server.py")]}}}))
        cmd = ["claude", "-p", "--output-format", "stream-json", "--include-partial-messages", "--verbose",
               "--strict-mcp-config", "--mcp-config", str(MCP_CONFIG), "--disable-slash-commands",
               "--allowedTools", TOOLS, "--append-system-prompt", SYSTEM_PROMPT]
        if self.model:
            cmd += ["--model", self.model]
        resumed = SESSION_FILE.exists()
        if resumed:
            cmd += ["--resume", SESSION_FILE.read_text().strip()]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=STATE_DIR)
        timer = threading.Timer(self.claude_timeout, proc.kill)
        timer.start()
        result = None
        spoken = False
        buf = ""
        streamed = ""

        def flush(final):
            nonlocal buf, spoken
            while True:
                m = re.search(r"[.!?](\s|$)", buf)
                if not m or (m.end() == len(buf) and not final and m.group(1) == ""):
                    break
                sentence, buf = buf[:m.end()].strip(), buf[m.end():]
                if sentence:
                    say(sentence)
                    spoken = True
            if final and buf.strip():
                say(buf.strip())
                spoken = True
                buf = ""

        try:
            proc.stdin.write(text)
            proc.stdin.close()
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "stream_event":
                    e = ev.get("event", {})
                    if e.get("type") == "content_block_delta" and e["delta"].get("type") == "text_delta":
                        buf += e["delta"]["text"]
                        streamed += e["delta"]["text"]
                        self.caption = f"{self._question}\nClaude: " + (("..." + streamed[-400:]) if len(streamed) > 400 else streamed)  # shown live in the banner
                        print(e["delta"]["text"], end="", flush=True)
                        flush(False)
                    elif e.get("type") == "content_block_stop":
                        flush(True)  # end of a text block (or tool call): speak what is left
                elif ev.get("type") == "result":
                    result = ev
            proc.wait(timeout=5)
        except Exception as e:
            print(f"claude stream error: {e}", flush=True)
        finally:
            timer.cancel()
            proc.kill()
        flush(True)
        if result is None or result.get("is_error"):
            print(f"claude failed: {proc.stderr.read()[:300]}", flush=True)
            if resumed:
                SESSION_FILE.unlink(missing_ok=True)  # a stale session id: the next question starts fresh
            reply = "Sorry, I could not reach Claude." if result is None else "Sorry, something went wrong."
            say(reply)
            return reply
        if result.get("session_id"):
            SESSION_FILE.write_text(result["session_id"])
        reply = str(result.get("result") or "")
        if not spoken:
            reply = reply or "Sorry, I have no answer."
            say(reply)
        return reply

    # ---- speech out -------------------------------------------------------------------------
    def _start_speaker(self):
        """Returns (say, finish): say(sentence) queues speech as it arrives, finish() waits until it has all played."""
        q = queue.Queue()

        def worker():
            while (sentence := q.get()) is not None:
                if self._stop.is_set():
                    continue
                self.status = "speaking"
                clean = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", sentence)
                clean = re.sub(r"[*_`#>]", "", clean).strip()
                if not clean:
                    continue
                try:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        with wave.open(f, "wb") as w:
                            self._piper.synthesize_wav(clean, w)
                    subprocess.run(["pw-play", f.name], timeout=60, stderr=subprocess.DEVNULL)
                except Exception as e:
                    print(f"speech error: {e}", flush=True)
                finally:
                    Path(f.name).unlink(missing_ok=True)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        def finish():
            q.put(None)
            t.join(timeout=120)
            time.sleep(0.3)  # let the room tail off before the mic reopens

        return q.put, finish
