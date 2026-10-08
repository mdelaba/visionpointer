"""Shared on-disk contract between the pointer (writer) and agent adapters like the MCP server (readers).

selection.json  -> {"selection": {...} | null, "cleared_at": ts?}   latest sticky selection
history.jsonl   -> one selection per line, oldest first
Override the directory with the VP_STATE_DIR environment variable.
"""
import json
import os
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("VP_STATE_DIR", "~/.cache/visionpointer")).expanduser()
SELECTION_FILE = STATE_DIR / "selection.json"
HISTORY_FILE = STATE_DIR / "history.jsonl"


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


def clear_selection() -> None:
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
