"""Shared on-disk contract between the pointer (writer) and agent adapters like the MCP server (readers).

selection.json  -> {"selection": {...} | null, "cleared_at": ts?}   latest sticky selection
history.jsonl   -> one selection per line, oldest first
Override the directory with the VP_STATE_DIR environment variable.
"""
import json
import os
import shutil
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("VP_STATE_DIR", "~/.cache/visionpointer")).expanduser()
SELECTION_FILE = STATE_DIR / "selection.json"
HISTORY_FILE = STATE_DIR / "history.jsonl"
SCREENSHOT_DIR = STATE_DIR / "screenshots"  # only written with web_pointer --screenshots


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def write_selection(element: dict) -> None:
    selection = {"selected_at": time.time(), **element}
    _write_atomic(SELECTION_FILE, json.dumps({"selection": selection}))
    with HISTORY_FILE.open("a") as f:
        f.write(json.dumps(selection) + "\n")


def attach_screenshot(selected_at: float, shot: dict) -> bool:
    """Add screenshot info to the selection made at selected_at (current file and its history line)."""
    try:
        data = json.loads(SELECTION_FILE.read_text())
        sel = data.get("selection")
    except (OSError, ValueError):
        return False
    if not sel or sel.get("selected_at") != selected_at:
        return False  # the selection changed while the screenshot was being taken
    sel["screenshot"] = shot
    _write_atomic(SELECTION_FILE, json.dumps({"selection": sel}))
    try:
        lines = HISTORY_FILE.read_text().splitlines()
        if lines and json.loads(lines[-1]).get("selected_at") == selected_at:
            lines[-1] = json.dumps(sel)
            _write_atomic(HISTORY_FILE, "\n".join(lines) + "\n")
    except (OSError, ValueError):
        pass
    return True


def clear_screenshots() -> None:
    shutil.rmtree(SCREENSHOT_DIR, ignore_errors=True)


def clear_selection() -> None:
    clear_screenshots()  # screenshots can show private page content: do not keep them once the selection is gone
    _write_atomic(SELECTION_FILE, json.dumps({"selection": None, "cleared_at": time.time()}))


def read_selection():
    """Return the current selection dict (with age_seconds added), or None."""
    try:
        sel = json.loads(SELECTION_FILE.read_text()).get("selection")
    except (OSError, ValueError):
        return None
    if sel:
        sel["age_seconds"] = round(time.time() - sel["selected_at"], 1)
    return sel


def read_history(limit: int = 5) -> list:
    try:
        lines = HISTORY_FILE.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out[::-1]  # newest first
