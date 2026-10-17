# YellowPage

A small toy project for learning how MCP works, built around a notes app.

The name comes from the *Yellow Pages*: a public directory you search by what you
are after, rather than by who you already know. Notes here work the same way —
everyone's are listed for everyone, and you find them by meaning rather than by
exact wording.

There are two front doors onto **one** SQLite database:

- a **Flask web app** (`app.py`) that humans use — this is where accounts live and
  where notes are created, edited and deleted;
- an **MCP server** (`server.py`) that LLM clients connect to — a read-only
  window onto the same notes.

The idea is that the MCP server is a "USB port for LLMs": plug any MCP client in
and it can read the notes, but it can't change them, because an MCP client has no
logged-in user attached to it.

Notes can also be found **by meaning** rather than by keyword — a query like
"what did I learn about GPU memory?" turns up a note called "CUDA VRAM basics".
See [Semantic search](#semantic-search).

## Access rules

| Action | Who can do it |
| --- | --- |
| Register an account | Anyone |
| Log in / log out | Anyone with valid credentials |
| Read any note (list, detail) | Anyone, logged in or not |
| Search notes | Anyone, logged in or not |
| Create a note | Any logged-in user (recorded as the owner) |
| Edit / delete a note | **Only its owner** |

Every note has an `owner_id`, so ownership is enforced in `notes.py` and surfaced
in the UI (the Flask app returns `403` and hides the buttons when a note isn't
yours).

## Project layout

```
mcp-learn/
├── app.py            Flask UI: register / login / logout + notes CRUD + search
├── auth.py           User accounts: registration and password checking
├── notes.py          Note CRUD with ownership rules
├── search.py         Semantic search: embeddings, storage and ranking
├── db.py             Shared SQLite connection + schema
├── server.py         MCP server (read-only tools for LLM clients)
├── templates/        Jinja templates for the Flask app
│   ├── base.html
│   ├── index.html
│   ├── note.html
│   ├── form.html     Shared by "new note" and "edit note"
│   ├── search.html   Semantic search results
│   ├── _search_form.html   Search box, included by index.html and search.html
│   ├── login.html
│   └── register.html
├── static/
│   └── style.css     Stylesheet for the Flask pages (light and dark)
├── .cache/fastembed/ Downloaded model weights (not in version control)
├── opencode.json     Registers the MCP server with OpenCode
├── requirements.txt  Direct dependencies, pinned
└── notes.db          SQLite database (not in version control)
```

The layering is deliberate: `db.py`, `auth.py`, `notes.py` and `search.py` are
plain Python with no knowledge of Flask or MCP. `app.py` and `server.py` are thin
wrappers around them.

## Setup

Python 3.10 or newer is required (the code uses `X | None` type hints).

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Running

### Web app

```powershell
.venv\Scripts\python.exe app.py
```

Then open <http://127.0.0.1:5000>. Register a couple of accounts, create a note
with each, and you will see one user's note in the other's list — readable, but
without Edit/Delete buttons.

### MCP server

`opencode.json` already registers it as `yellowpage` (and `.vscode/mcp.json` does
the same for VS Code). Restart OpenCode after editing `server.py` so it picks up
the new tools. To run it by hand:

```powershell
.venv\Scripts\python.exe server.py
```

Exposed tools:

| Tool | Description |
| --- | --- |
| `hello_mcp` | Smoke test that the server is alive. |
| `get_project_info` | Returns a short description of the project. |
| `list_notes` | Every note, most recently updated first, with its owner. |
| `read_note` | One note by id, with its owner and timestamps. |
| `search_notes` | Find notes by meaning; each result carries a similarity `score`. |

Note there are **no** user-management tools and **no** write tools on the MCP
side, by design.

## Semantic search

Searching by keyword breaks as soon as you describe a topic instead of quoting
it. "What did I learn about GPU memory?" shares no words with a note called "CUDA
VRAM basics", yet that is obviously the note you want.

`search.py` closes that gap by comparing **meaning**:

1. Every note is turned into a vector (384 numbers) by a local embedding model,
   `BAAI/bge-small-en-v1.5`, run on the CPU by [fastembed](https://github.com/qdrant/fastembed).
   No API key, and no network after the first download.
2. Vectors are stored in the `note_embeddings` table of `notes.db` as float32
   BLOBs, one row per note. They are stored already normalised.
3. A query is embedded with the model's *query* path (BGE models frame queries
   differently from documents), and every note is scored by cosine similarity —
   which is a plain dot product, because the vectors are normalised.
4. The highest scores come back first, each with its `score` attached.

At this scale the ranking is a numpy pass over every vector, which is instant. A
dedicated vector database only starts to pay off at millions of notes; the design
here is deliberately simple so you can see the whole pipeline.

From the web app, use the search box on the home page (or the **Search** link in
the nav). From the command line:

```powershell
.venv\Scripts\python.exe search.py search "what did I learn about gpu memory"
.venv\Scripts\python.exe search.py search "baking bread" -n 3
.venv\Scripts\python.exe search.py reindex
```

Notes created or edited through the Flask app are embedded on the fly. Run
`reindex` after pulling changes, after adding notes straight to the database, or
after changing the model. Switching models is safe: `reindex` clears vectors that
belong to a different model first, so two vector spaces never mix.

The model weights are downloaded once, on first use, into `.cache/fastembed/`
inside the project. That directory is git-ignored and safe to delete; the next
search will re-fetch it. Set `NOTES_EMBED_MODEL` to try a different model.

## Database

`notes.db` is created automatically on first run. Three tables:

```sql
users (id, username UNIQUE, password_hash, created_at)

notes (id, owner_id -> users(id), title, content, created_at, updated_at)

note_embeddings (note_id -> notes(id), model, dim, vector BLOB, updated_at)
```

Passwords are never stored in plain text; `auth.py` keeps a salted hash produced
by `werkzeug.security`. Deleting a user cascades to their notes, and deleting a
note takes its embedding row with it (`ON DELETE CASCADE`).

To start over, just delete the file:

```powershell
Remove-Item notes.db
```

To peek at it without a SQLite client installed, use the standard library:

```powershell
.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('notes.db'); print(c.execute('SELECT * FROM notes').fetchall())"
```

## Known limitations

This is a teaching project, not production software:

- **No CSRF protection.** Add Flask-WTF (or equivalent) before exposing it.
- **Default secret key.** `app.secret_key` falls back to `"dev-secret-change-me"`.
  Set the `NOTES_SECRET_KEY` environment variable instead.
- **`debug=True`** is hard-coded in `app.run()` for local development.
- **No rate limiting** on login attempts.
- The MCP server is read-only on purpose, so it cannot satisfy "only the owner
  may edit" — there is no user context on that path.
- **Search ranks with a brute-force numpy pass** over every vector, which is
  instant here but would want a real vector index at a much larger scale.
- **The first search downloads ~130 MB** of model weights. After that it is
  offline.
- **Embeddings belong to a model.** Change `NOTES_EMBED_MODEL` and you must run
  `search.py reindex`; query and document vectors from different models are not
  comparable.
- **Semantic search only.** There is no keyword/hybrid blending or reranking step
  yet, so an exact phrase can occasionally lose to a semantically close note.
