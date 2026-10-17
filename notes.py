"""CRUD helpers for the notes database.

Nothing in this module knows about Flask or MCP. Every function is plain Python
so it can be reused from a script or unit tested on its own.

Access rules
------------
* Anybody may :func:`list_notes` and :func:`read_note` — every user can read
  every other user's notes.
* Creating a note records the creator as its ``owner_id``.
* :func:`edit_note` and :func:`delete_note` take the acting user's id and raise
  :class:`PermissionError` unless that user owns the note.
"""

from __future__ import annotations

import sqlite3

import db

_SELECT = """
SELECT n.id, n.title, n.content, n.owner_id, n.created_at, n.updated_at,
       u.username AS owner
  FROM notes AS n
  JOIN users AS u ON u.id = n.owner_id
"""


def _fetch(conn: sqlite3.Connection, note_id: int) -> dict:
    """Return one note as a dict, or raise ValueError if it does not exist."""
    row = conn.execute(f"{_SELECT} WHERE n.id = ?", (note_id,)).fetchone()
    if row is None:
        raise ValueError(f"no note with id {note_id}")
    return dict(row)


def _require_owner(note: dict, user_id: int) -> None:
    """Raise PermissionError unless ``user_id`` owns ``note``."""
    if note["owner_id"] != user_id:
        raise PermissionError("you can only change notes that you own")


def _clean_title(title: str | None) -> str:
    title = (title or "").strip()
    if not title:
        raise ValueError("title must not be empty")
    return title


def list_notes() -> list[dict]:
    """Return every note, most recently updated first."""
    with db.connect() as conn:
        rows = conn.execute(f"{_SELECT} ORDER BY n.updated_at DESC, n.id DESC").fetchall()
    return [dict(row) for row in rows]


def list_notes_by_owner(owner_id: int) -> list[dict]:
    """Return only the notes owned by one user, most recently updated first."""
    with db.connect() as conn:
        rows = conn.execute(
            f"{_SELECT} WHERE n.owner_id = ? ORDER BY n.updated_at DESC, n.id DESC",
            (owner_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def read_note(note_id: int) -> dict:
    """Return a single note. Reading is open to everyone."""
    with db.connect() as conn:
        return _fetch(conn, note_id)


def create_note(owner_id: int, title: str, content: str = "") -> dict:
    """Create a note owned by ``owner_id`` and return it, including its new id."""
    title = _clean_title(title)
    stamp = db.now()
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO notes (owner_id, title, content, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (owner_id, title, content, stamp, stamp),
        )
        return _fetch(conn, cursor.lastrowid)


def edit_note(
    user_id: int,
    note_id: int,
    title: str | None = None,
    content: str | None = None,
) -> dict:
    """Change a note's ``title`` and/or ``content``; return the updated note.

    Fields left as ``None`` keep their current value. Raises ``PermissionError``
    when ``user_id`` does not own the note.
    """
    if title is None and content is None:
        raise ValueError("pass a new title and/or content to edit")

    with db.connect() as conn:
        note = _fetch(conn, note_id)
        _require_owner(note, user_id)

        new_title = note["title"] if title is None else _clean_title(title)
        new_content = note["content"] if content is None else content

        conn.execute(
            "UPDATE notes SET title = ?, content = ?, updated_at = ? WHERE id = ?",
            (new_title, new_content, db.now(), note_id),
        )
        return _fetch(conn, note_id)


def delete_note(user_id: int, note_id: int) -> dict:
    """Delete a note and return it. Raises ``PermissionError`` if not the owner."""
    with db.connect() as conn:
        note = _fetch(conn, note_id)
        _require_owner(note, user_id)
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    return note
