"""Semantic search over the notes.

Instead of matching keywords, every note is turned into a *vector* — a list of
numbers that stands in for its meaning — by a local embedding model, and a query
is turned into a vector the same way. Notes whose vectors point in a similar
direction to the query's come back first. That is why "what did I learn about
GPU memory?" can find a note titled "CUDA VRAM basics" even though the two share
no words.

How the pieces fit together:

* the model comes from ``fastembed``, which runs a small ONNX model on the CPU —
  no API key, and no network after the first download;
* vectors live in the ``note_embeddings`` table in ``notes.db`` as float32
  BLOBs, one row per note;
* ranking is cosine similarity computed with numpy over every stored vector at
  once. Because vectors are stored already normalised, that is just a dot
  product. At this scale it is instant; a dedicated vector database would start
  to matter at millions of notes, not hundreds.

This module owns both halves of the feature — keeping the vectors current
(:func:`index_note`, :func:`remove_note`, :func:`reindex_all`) and querying them
(:func:`search`). ``app.py`` re-indexes on every write; the Flask search page and
the MCP server both call :func:`search`.

From the command line::

    python search.py reindex                    # (re)build every embedding
    python search.py search "gpu memory"        # try a query
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np

import db
import notes

# Hugging Face warns on every download that Windows will not create symlinks for
# its cache. Caching still works, it just copies files, so hide the noise.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

#: Local model, overridable for experiments. Changing it invalidates every
#: stored vector, which ``reindex_all`` clears out for you.
MODEL_NAME = os.environ.get("NOTES_EMBED_MODEL", "BAAI/bge-small-en-v1.5")

#: Model weights are downloaded here on first use, kept inside the project so the
#: cache is easy to find and easy to delete. Git-ignored.
CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "fastembed"

DEFAULT_LIMIT = 5


@lru_cache(maxsize=1)
def _model():
    """Load the embedding model once per process (it is slow to build)."""
    from fastembed import TextEmbedding

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return TextEmbedding(model_name=MODEL_NAME, cache_dir=str(CACHE_DIR))


def _note_text(note: dict) -> str:
    """The text a note is embedded from: its title, then its body."""
    return f"{note['title']}\n\n{note['content']}".strip()


def _normalise(vector) -> np.ndarray:
    """Scale a vector to unit length so cosine similarity is a dot product."""
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0.0 else vector / norm


def _embed_documents(texts: list[str]) -> list[np.ndarray]:
    """Embed notes/passages. ``embed`` is the document side of the model."""
    if not texts:
        return []
    return [_normalise(vector) for vector in _model().embed(texts)]


def _embed_query(query: str) -> np.ndarray:
    """Embed a search query.

    Some models (the BGE family among them) expect queries to be framed
    differently from documents, which is exactly what ``query_embed`` handles.
    """
    return _normalise(next(iter(_model().query_embed(query))))


def _store(conn, note_id: int, vector: np.ndarray) -> None:
    """Insert or replace one note's vector."""
    conn.execute(
        """
        INSERT INTO note_embeddings (note_id, model, dim, vector, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(note_id) DO UPDATE SET
            model      = excluded.model,
            dim        = excluded.dim,
            vector     = excluded.vector,
            updated_at = excluded.updated_at
        """,
        (note_id, MODEL_NAME, int(vector.shape[0]), vector.tobytes(), db.now()),
    )


def index_note(note_id: int) -> None:
    """(Re)compute and store the embedding for a single note."""
    note = notes.read_note(note_id)
    vector = _embed_documents([_note_text(note)])[0]
    with db.connect() as conn:
        _store(conn, note_id, vector)


def remove_note(note_id: int) -> None:
    """Drop a note's embedding.

    Deleting the note itself takes the row with it (``ON DELETE CASCADE``), so
    this is only needed if a note were to stay without being indexed.
    """
    with db.connect() as conn:
        conn.execute("DELETE FROM note_embeddings WHERE note_id = ?", (note_id,))


def reindex_all() -> int:
    """Rebuild every embedding and return how many notes were indexed.

    Vectors left behind by a *different* model are cleared first, so two vector
    spaces never get mixed in the same table.
    """
    all_notes = notes.list_notes()
    vectors = _embed_documents([_note_text(note) for note in all_notes])
    with db.connect() as conn:
        conn.execute("DELETE FROM note_embeddings WHERE model != ?", (MODEL_NAME,))
        for note, vector in zip(all_notes, vectors):
            _store(conn, note["id"], vector)
    return len(all_notes)


def search(query: str, limit: int = DEFAULT_LIMIT, min_score: float = 0.0) -> list[dict]:
    """Return the notes that mean the most like ``query``, best first.

    Each result is the usual note dict plus a ``score`` between 0 and 1, where
    higher means closer in meaning. ``min_score`` drops weak matches.
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("search query must not be empty")
    if limit < 1:
        raise ValueError("limit must be at least 1")

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT note_id, vector FROM note_embeddings WHERE model = ?",
            (MODEL_NAME,),
        ).fetchall()

    if not rows:
        return []

    query_vector = _embed_query(query)
    matrix = np.stack(
        [np.frombuffer(row["vector"], dtype=np.float32) for row in rows]
    )

    # Every stored vector is unit length, so this dot product *is* the cosine
    # similarity between the query and each note.
    scores = matrix @ query_vector

    catalog = {note["id"]: note for note in notes.list_notes()}
    results: list[dict] = []
    for index in np.argsort(-scores)[:limit]:
        score = float(scores[index])
        note = catalog.get(rows[index]["note_id"])
        if note is None or score < min_score:
            continue
        results.append({**note, "score": score})
    return results


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Semantic search over the notes.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("reindex", help="(re)build the embedding for every note")
    search_parser = subparsers.add_parser("search", help="run a semantic query")
    search_parser.add_argument("query", nargs="+")
    search_parser.add_argument("-n", "--limit", type=int, default=DEFAULT_LIMIT)

    args = parser.parse_args(argv)

    if args.command == "reindex":
        print(f"indexed {reindex_all()} note(s) with {MODEL_NAME}")
        return 0

    hits = search(" ".join(args.query), limit=args.limit)
    if not hits:
        print("no matches")
        return 0
    for hit in hits:
        print(f"{hit['score']:.3f}  {hit['title']}  (by {hit['owner']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
