"""User accounts: registration and password checking.

Passwords are never stored as-is. We keep a salted hash produced by
``werkzeug.security`` (the same library Flask uses), and verify a login attempt
by re-hashing the supplied password and comparing.

Like ``notes.py`` this module knows nothing about Flask or MCP; ``app.py``
wraps these functions in routes.
"""

from __future__ import annotations

import sqlite3

from werkzeug.security import check_password_hash, generate_password_hash

import db

_MIN_PASSWORD = 4


def _public(row: sqlite3.Row | dict) -> dict:
    """Convert a user row to a dict, dropping the password hash."""
    user = dict(row)
    user.pop("password_hash", None)
    return user


def register(username: str, password: str) -> dict:
    """Create a new account and return it (without the password hash)."""
    username = (username or "").strip()
    if not username:
        raise ValueError("username must not be empty")
    if len(password or "") < _MIN_PASSWORD:
        raise ValueError(f"password must be at least {_MIN_PASSWORD} characters")

    with db.connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if exists is not None:
            raise ValueError(f"the username {username!r} is already taken")

        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, created_at)"
            " VALUES (?, ?, ?)",
            (username, generate_password_hash(password), db.now()),
        )
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return _public(row)


def authenticate(username: str, password: str) -> dict | None:
    """Return the user when the credentials match, otherwise ``None``."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            ((username or "").strip(),),
        ).fetchone()

    if row is None or not check_password_hash(row["password_hash"], password or ""):
        return None
    return _public(row)


def get_user(user_id: int) -> dict | None:
    """Return a user by id, or ``None`` if there is no such account."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return None if row is None else _public(row)
