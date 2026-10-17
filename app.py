"""Flask web UI: the "real" application.

A human uses this app. It handles account management (register / login /
logout) and the day-to-day note work, enforcing two rules:
* you must be logged in to create a note, and
* you may only edit or delete notes that you own,
while every note stays readable by everyone.

Run it with::

    .venv\\Scripts\\python.exe app.py

The MCP server (``server.py``) shares the same database through ``notes.py``.
"""

from __future__ import annotations

import os
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import auth
import notes
import search

app = Flask(__name__)
# In a real deployment set NOTES_SECRET_KEY; the default is only for local play.
app.secret_key = os.environ.get("NOTES_SECRET_KEY", "dev-secret-change-me")


@app.template_filter("date")
def format_date(value: str) -> str:
    """Render a stored ISO timestamp as a plain date, with no time of day.

    Templates show ``created_at|date`` so a note reads "16 Oct 2026" rather than
    the full timestamp. Anything unparsable is passed through unchanged.
    """
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return value


@app.before_request
def load_current_user() -> None:
    """Populate ``g.user`` from the session before each request."""
    user_id = session.get("user_id")
    g.user = auth.get_user(user_id) if user_id is not None else None
    if g.user is None:
        # The account may have been deleted, or the cookie is stale.
        session.pop("user_id", None)


def login_required(view):
    """Redirect anonymous visitors to the login page."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in first.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def safe_next(target: str | None) -> str:
    """Only allow redirecting back to a local page, never off-site."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("index")


def reauthenticate():
    """Guard the account forms: the current password must be supplied.

    Returns a response when the password is wrong, so callers can simply
    ``return reauthenticate()``. Changing details behind a borrowed session
    would otherwise be a way to lock somebody out of their own account.
    """
    if auth.verify_password(g.user["id"], request.form.get("current_password", "")):
        return None
    flash("That is not your current password.", "error")
    return render_template("account.html"), 400


def load_note_or_404(note_id: int) -> dict:
    try:
        return notes.read_note(note_id)
    except ValueError:
        abort(404)


def require_owner(note: dict) -> None:
    if note["owner_id"] != g.user["id"]:
        abort(403)


def index_for_search(note_id: int) -> None:
    """Embed a note so semantic search can find it.

    Best effort on purpose: a note that was saved is saved, and a warning about
    indexing is more useful than a 500 page if the model cannot be loaded.
    """
    try:
        search.index_note(note_id)
    except Exception as exc:  # noqa: BLE001 - report whatever went wrong as a flash
        flash(f"Saved, but search indexing failed: {exc}", "error")


# ---------------------------------------------------------------- accounts ---


@app.get("/register")
def register_form():
    return render_template("register.html")


@app.post("/register")
def register():
    try:
        auth.register(request.form["username"], request.form["password"])
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("register.html"), 400

    flash("Account created. You can log in now.", "success")
    return redirect(url_for("login"))


@app.get("/login")
def login_form():
    return render_template("login.html", next=request.args.get("next"))


@app.post("/login")
def login():
    user = auth.authenticate(request.form["username"], request.form["password"])
    if user is None:
        flash("Wrong username or password.", "error")
        return render_template("login.html", next=request.form.get("next")), 401

    session.clear()
    session["user_id"] = user["id"]
    flash(f"Welcome back, {user['username']}!", "success")
    return redirect(safe_next(request.form.get("next")))


@app.post("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.get("/account")
@login_required
def account_form():
    return render_template("account.html")


@app.post("/account/username")
@login_required
def change_username():
    wrong = reauthenticate()
    if wrong is not None:
        return wrong

    try:
        user = auth.change_username(g.user["id"], request.form.get("username", ""))
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("account.html"), 400

    flash(f"Your username is now {user['username']}.", "success")
    return redirect(url_for("account_form"))


@app.post("/account/password")
@login_required
def change_password():
    wrong = reauthenticate()
    if wrong is not None:
        return wrong

    try:
        auth.change_password(g.user["id"], request.form.get("new_password", ""))
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("account.html"), 400

    flash("Your password has been changed.", "success")
    return redirect(url_for("account_form"))


# ------------------------------------------------------------------- notes ---


@app.get("/")
def index():
    return render_template("index.html", notes=notes.list_notes())


@app.get("/search")
def search_page():
    query = request.args.get("q", "").strip()
    results = search.search(query, limit=20) if query else []
    return render_template("search.html", query=query, results=results)


@app.get("/notes/<int:note_id>")
def note_detail(note_id: int):
    return render_template("note.html", note=load_note_or_404(note_id))


@app.get("/notes/new")
@login_required
def new_note_form():
    return render_template("form.html", note=None)


@app.post("/notes/new")
@login_required
def new_note():
    try:
        note = notes.create_note(g.user["id"], request.form["title"], request.form.get("content", ""))
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("form.html", note=None), 400

    index_for_search(note["id"])
    flash("Note created.", "success")
    return redirect(url_for("note_detail", note_id=note["id"]))


@app.get("/notes/<int:note_id>/edit")
@login_required
def edit_note_form(note_id: int):
    note = load_note_or_404(note_id)
    require_owner(note)
    return render_template("form.html", note=note)


@app.post("/notes/<int:note_id>/edit")
@login_required
def edit_note(note_id: int):
    note = load_note_or_404(note_id)
    require_owner(note)
    try:
        notes.edit_note(
            g.user["id"],
            note_id,
            title=request.form["title"],
            content=request.form.get("content", ""),
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("form.html", note=note), 400

    index_for_search(note_id)
    flash("Note updated.", "success")
    return redirect(url_for("note_detail", note_id=note_id))


@app.post("/notes/<int:note_id>/delete")
@login_required
def delete_note(note_id: int):
    note = load_note_or_404(note_id)
    require_owner(note)
    # The note's embedding goes with it, via ON DELETE CASCADE.
    notes.delete_note(g.user["id"], note_id)
    flash("Note deleted.", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
