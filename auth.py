"""User accounts: registration, sign-in, and changing your own details.

Passwords are never stored as-is. We keep a salted hash produced by
``werkzeug.security`` (the same library Flask uses), and verify a login attempt
by re-hashing the supplied password and comparing.

Like ``notes.py`` this module knows nothing about Flask or MCP; ``app.py``
wraps these functions in routes.

Renaming an account needs no extra work elsewhere: notes look up their owner's
name through a join, so every note a user owns follows the new name
immediately.
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


def _clean_username(username: str) -> str:
    username = (username or "").strip()
    if not username:
        raise ValueError("username must not be empty")
    return username


def _clean_password(password: str) -> str:
    password = password or ""
    if len(password) < _MIN_PASSWORD:
        raise ValueError(f"password must be at least {_MIN_PASSWORD} characters")
    return password


def _taken(conn: sqlite3.Connection, username: str, exclude_id: int | None = None) -> bool:
    """Whether a username is in use by somebody other than ``exclude_id``.

    Comparing with COLLATE NOCASE means "Alice" and "alice" count as the same
    name, so a rename cannot squat on a case variant of an existing account.
    """
    row = conn.execute(
        "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()
    return row is not None and row["id"] != exclude_id


def _load(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ValueError(f"no user with id {user_id}")
    return row


def register(username: str, password: str) -> dict:
    """Create a new account and return it (without the password hash)."""
    username = _clean_username(username)
    password = _clean_password(password)

    with db.connect() as conn:
        if _taken(conn, username):
            raise ValueError(f"the username {username!r} is already taken")

        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, created_at)"
            " VALUES (?, ?, ?)",
            (username, generate_password_hash(password), db.now()),
        )
        row = _load(conn, cursor.lastrowid)
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


def verify_password(user_id: int, password: str) -> bool:
    """Whether ``password`` is the current password for ``user_id``.

    Callers use this to re-authenticate before letting somebody change their
    details, so a borrowed session cannot be used to lock the owner out.
    """
    with db.connect() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return row is not None and check_password_hash(row["password_hash"], password or "")


def change_username(user_id: int, new_username: str) -> dict:
    """Rename an account and return it. The new name must not already be taken."""
    new_username = _clean_username(new_username)

    with db.connect() as conn:
        if _taken(conn, new_username, exclude_id=user_id):
            raise ValueError(f"the username {new_username!r} is already taken")
        conn.execute(
            "UPDATE users SET username = ? WHERE id = ?", (new_username, user_id)
        )
        return _public(_load(conn, user_id))


def change_password(user_id: int, new_password: str) -> dict:
    """Replace the stored password hash for an account."""
    new_password = _clean_password(new_password)

    with db.connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user_id),
        )
        return _public(_load(conn, user_id))
