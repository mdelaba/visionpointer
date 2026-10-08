"""MCP server exposing the element the user selected with VisionPointer (stdio).

Read-only: it only reads the state files written by web_pointer.py (see selection_store.py).
Register with Claude Code:  claude mcp add visionpointer -- <repo>/.venv/bin/python <repo>/src/mcp_server.py
"""
import json
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import Image, MCPServer

import selection_store

mcp = MCPServer(
    "visionpointer",
    instructions=(
        "VisionPointer lets the user point at and pinch-select a web element on their screen. "
        "When the user says 'this', 'that', 'here' or asks about something they are pointing at, "
        "call get_selected_element to see which element they mean."
    ),
)


@mcp.tool()
def get_selected_element() -> dict:
    """Return the web element the user currently has selected (highlighted green on their screen).

    Use this to resolve 'this', 'that' or 'it' in the user's request. The result has the CSS
    selector, tag, visible text, attributes, HTML snippet, bounding box (viewport pixels), the page
    url/title, and age_seconds since it was selected. If age_seconds is large the user may have
    moved on, so confirm with them when it matters.
    """
    selection = selection_store.read_selection()
    if selection is None:
        return {"selected": False, "message": "The user has no element selected right now."}
    return {"selected": True, **selection}


@mcp.tool()
def get_selection_history(limit: int = 5) -> list:
    """Return the user's most recent selections, newest first (default 5, max 20)."""
    return selection_store.read_history(max(1, min(limit, 20)))


@mcp.tool()
def get_selection_screenshot(view: Literal["annotated", "crop", "clean"] = "annotated") -> list:
    """Return a screenshot of the page as it was when the user selected the current element.

    Only call this when the question needs to SEE the page (what an image or chart shows, colours,
    layout, where something is). Text questions are answered by get_selected_element alone.
    view: 'annotated' = whole visible page with a red box around the selected element and a crosshair
    where the user pointed; 'crop' = just the element with a small margin; 'clean' = whole page, no marks.
    The text result gives the element's box and the pointer position in image pixels and as 0-1 fractions.
    Needs web_pointer started with --screenshots.
    """
    selection = selection_store.read_selection()
    if selection is None:
        return ["The user has no element selected right now."]
    shot = selection.get("screenshot")
    if not shot:
        return ["No screenshot is available: web_pointer must be started with --screenshots (it is off by default for privacy)."]
    path = Path(shot.get(view, ""))
    if not path.is_file():
        return ["The screenshot file is gone (it is deleted when the selection is cleared)."]
    info = {k: v for k, v in shot.items() if k not in ("annotated", "crop", "clean")}
    info.update(view=view, age_seconds=selection["age_seconds"], page=selection["page"]["url"])
    return [Image(path=path), json.dumps(info)]


if __name__ == "__main__":
    mcp.run()
