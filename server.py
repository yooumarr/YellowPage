"""MCP server: a read-only window onto the notes database for LLM clients.

This is the "USB port" side of the project. It deliberately exposes **no**
user-management tools and **no** way to write, because an MCP client has no
logged-in user attached to it — so it could never satisfy the rule that only an
owner may edit their own notes.

Accounts and note editing live in the Flask app (``app.py``). Anything an LLM
client can do here is read: list every note, read one by id, or search them by
meaning.
"""

from fastmcp import FastMCP

import notes
import search

mcp = FastMCP("YellowPage")


@mcp.tool()
def hello_mcp(name: str) -> str:
    """Greet a user and confirm that the MCP server is running."""
    return f"Hello {name}! The MCP server is running."


@mcp.tool()
def get_project_info() -> str:
    """Return a short description of this project."""
    return "this project is a toy project that shows how mcps work."


@mcp.tool()
def read_note(note_id: int) -> dict:
    """Read one note by its id. Includes the note's owner and timestamps."""
    return notes.read_note(note_id)


@mcp.tool()
def list_notes() -> list[dict]:
    """List every note, most recently updated first, with its owner."""
    return notes.list_notes()


@mcp.tool()
def search_notes(query: str, limit: int = 5) -> list[dict]:
    """Find notes by meaning rather than exact keywords.

    Use this when you know roughly what you are looking for but not which words
    the note used. For example, a query like "what did I learn about GPU
    memory?" can return a note titled "CUDA VRAM basics". Each result is a note
    plus a ``score`` (higher means a closer match).
    """
    return search.search(query, limit=limit)


if __name__ == "__main__":
    mcp.run()
