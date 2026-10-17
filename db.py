"""Database connection and schema.

``app.py`` (the Flask UI) and ``server.py`` (the MCP server) both import this
module so they agree on where the database lives and what shape it has.

Schema
------
users
    One row per account. Only the *hash* of the password is stored.
notes
    One row per note. ``owner_id`` points at the account that created it, so we
    can decide who is allowed to edit or delete a note. Every note has an owner.
note_embeddings
    One row per note, holding that note's vector as a float32 BLOB. Kept in a
    separate table so the notes table stays readable without numpy, and so a
    change of embedding model can be detected (and rebuilt) by comparing
    ``model``/``dim``. The row is deleted along with its note.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "notes.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS note_embeddings (
    note_id    INTEGER PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    dim        INTEGER NOT NULL,
    vector     BLOB NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open the database, hand out one connection, commit, then close it."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def now() -> str:
    """Current time as an ISO-8601 UTC string, used for the timestamp columns."""
    return datetime.now(timezone.utc).isoformat()
