"""MCP server exposing the element the user selected with VisionPointer (stdio).

Read-only: it only reads the state files written by web_pointer.py (see selection_store.py).
Register with Claude Code:  claude mcp add visionpointer -- <repo>/.venv/bin/python <repo>/src/mcp_server.py
"""
from mcp.server.mcpserver import MCPServer

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


if __name__ == "__main__":
    mcp.run()
