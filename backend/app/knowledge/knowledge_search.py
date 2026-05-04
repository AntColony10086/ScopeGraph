"""Hybrid (semantic + lexical) search over the local Markdown knowledge base.

The corpus lives at ``<repo>/data/knowledge/**/*.md``. On first use the
files are sliced into ~500-character chunks (paragraph boundaries
preserved) and embedded with the multilingual MiniLM model that the rest
of the project already pulls in. Queries are answered in two passes:

1. Cosine similarity against the cached embeddings narrows the corpus
   down to a handful of candidates.
2. The candidates are re-ranked by Jaccard similarity over **Chinese
   characters** — a cheap lexical signal that complements the embedding
   model's bag-of-meaning view on Mandarin queries.

The final score is a fixed convex combination ``0.7 * cos + 0.3 * jaccard``.

Module-level state is rebuilt lazily and cached. Failures at the disk /
model boundary degrade gracefully: the search returns ``[]`` and logs a
warning rather than raising into the request handler.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypedDict, cast

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
# The knowledge base is a sibling of the ``backend/`` package. From this
# file: app/knowledge/knowledge_search.py
#                   parents[0]   -> .../app/knowledge
#                   parents[1]   -> .../app
#                   parents[2]   -> .../backend
#                   parents[3]   -> .../<repo root>
_KNOWLEDGE_DIR: Final[Path] = (
    Path(__file__).resolve().parents[3] / "data" / "knowledge"
)

_TARGET_CHUNK_CHARS: Final[int] = 500
_EMBED_MODEL_NAME: Final[str] = "paraphrase-multilingual-MiniLM-L12-v2"

_COSINE_WEIGHT: Final[float] = 0.7
_JACCARD_WEIGHT: Final[float] = 0.3
_CANDIDATE_MULTIPLIER: Final[int] = 3

# Matches a single CJK Unified Ideograph (BMP block). Good enough for the
# Chinese knowledge corpus we're indexing here.
_CJK_RE: Final[re.Pattern[str]] = re.compile(r"[一-鿿]")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------
class Document(TypedDict):
    """One indexed chunk of a Markdown file.

    Attributes:
        text: The verbatim chunk text.
        source: Path of the source file relative to the knowledge root.
        embedding: L2-normalised sentence embedding for ``text``.
    """

    text: str
    source: str
    embedding: NDArray[np.float32]


@dataclass(slots=True, frozen=True)
class SearchHit:
    """A single result row returned by :func:`hybrid_search`.

    Attributes:
        text: The chunk text that matched.
        source: File the chunk came from, relative to the knowledge root.
        score: Final blended score in roughly ``[0, 1]``. Higher is better.
    """

    text: str
    source: str
    score: float


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------
_index: list[Document] | None = None
_embed_model: Any | None = None  # SentenceTransformer; typed as Any to keep
                                 # the import lazy.


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------
def _split_into_chunks(text: str, target_chars: int = _TARGET_CHUNK_CHARS) -> list[str]:
    """Slice a document into ~``target_chars`` chunks at paragraph boundaries.

    Paragraphs are joined greedily until adding the next one would exceed
    ``target_chars``. A paragraph that is itself larger than the budget is
    emitted as its own chunk untouched — splitting mid-paragraph would
    likely sever a sentence and is forbidden by the spec.

    Args:
        text: Raw file contents.
        target_chars: Soft upper bound on each chunk's length.

    Returns:
        A list of non-empty chunk strings, in source order.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    buffer: list[str] = []
    buffer_len = 0

    for paragraph in paragraphs:
        para_len = len(paragraph)
        if buffer and buffer_len + para_len + 2 > target_chars:
            chunks.append("\n\n".join(buffer))
            buffer = [paragraph]
            buffer_len = para_len
        else:
            buffer.append(paragraph)
            # +2 for the joining "\n\n" between paragraphs.
            buffer_len += para_len + (2 if buffer_len else 0)

    if buffer:
        chunks.append("\n\n".join(buffer))

    return chunks


def _get_embed_model() -> Any | None:
    """Lazily load the sentence-transformers model.

    Returns:
        The loaded ``SentenceTransformer`` instance, or ``None`` if the
        model could not be loaded (network blocked, package missing, ...).
        The failure is logged once at ``WARNING`` level.
    """
    global _embed_model
    if _embed_model is not None:
        return _embed_model

    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # noqa: BLE001 — optional dependency at runtime
        logger.warning("sentence-transformers not importable: %s", exc)
        return None

    try:
        _embed_model = SentenceTransformer(_EMBED_MODEL_NAME)
    except Exception as exc:  # noqa: BLE001 — model download / load
        logger.warning(
            "Failed to load embedding model %r: %s", _EMBED_MODEL_NAME, exc
        )
        return None

    logger.info("Loaded embedding model %s", _EMBED_MODEL_NAME)
    return _embed_model


def _build_index() -> list[Document]:
    """Walk the knowledge directory and build the embedded chunk index.

    Returns:
        One :class:`Document` per chunk. Returns an empty list if the
        knowledge directory is missing, has no Markdown content, or the
        embedding model is unavailable.
    """
    if not _KNOWLEDGE_DIR.exists():
        logger.warning("Knowledge directory does not exist: %s", _KNOWLEDGE_DIR)
        return []

    md_files = sorted(_KNOWLEDGE_DIR.rglob("*.md"))
    if not md_files:
        logger.warning("Knowledge directory %s has no .md files", _KNOWLEDGE_DIR)
        return []

    raw_chunks: list[tuple[str, str]] = []  # (source, text)
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read %s: %s", md_file, exc)
            continue

        rel_source = str(md_file.relative_to(_KNOWLEDGE_DIR))
        for chunk in _split_into_chunks(content):
            raw_chunks.append((rel_source, chunk))

    if not raw_chunks:
        logger.warning("Knowledge directory yielded zero chunks")
        return []

    model = _get_embed_model()
    if model is None:
        return []

    texts = [chunk for _, chunk in raw_chunks]
    try:
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    except Exception as exc:  # noqa: BLE001 — model boundary
        logger.warning("Embedding generation failed: %s", exc)
        return []

    arr = np.asarray(embeddings, dtype=np.float32)
    documents: list[Document] = [
        {
            "text": text,
            "source": source,
            "embedding": arr[i],
        }
        for i, (source, text) in enumerate(raw_chunks)
    ]
    logger.info(
        "Built knowledge index: %d chunks from %d files",
        len(documents),
        len(md_files),
    )
    return documents


def _ensure_index() -> list[Document]:
    """Return the cached index, building it on first call.

    Returns:
        The (possibly empty) list of indexed documents.
    """
    global _index
    if _index is None:
        _index = _build_index()
    return _index


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
def _cjk_charset(s: str) -> set[str]:
    """Return the set of distinct CJK characters in ``s``.

    Non-CJK characters (latin letters, punctuation, whitespace, digits)
    are intentionally ignored — Jaccard over a Chinese-character set is a
    cheap, robust similarity for the Mandarin queries this system serves.

    Args:
        s: Arbitrary text.

    Returns:
        A set of single-character strings, possibly empty.
    """
    return set(_CJK_RE.findall(s))


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two sets, defined as 0 when both are empty.

    Args:
        a: First set.
        b: Second set.

    Returns:
        ``|a ∩ b| / |a ∪ b|``, or ``0.0`` if either side is empty.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _embed_query(query: str) -> NDArray[np.float32] | None:
    """Embed a query string, returning ``None`` on failure.

    Args:
        query: The user's search query.

    Returns:
        A 1-D ``float32`` array (already L2-normalised by the model) or
        ``None`` if the embedding model is unavailable.
    """
    model = _get_embed_model()
    if model is None:
        return None
    try:
        vec = model.encode(
            [query], normalize_embeddings=True, show_progress_bar=False
        )
    except Exception as exc:  # noqa: BLE001 — model boundary
        logger.warning("Query embedding failed: %s", exc)
        return None
    arr: NDArray[np.float32] = np.asarray(vec, dtype=np.float32)
    return cast("NDArray[np.float32]", arr[0])


# ---------------------------------------------------------------------------
# Public API — new
# ---------------------------------------------------------------------------
async def hybrid_search(query: str, top_k: int = 5) -> list[SearchHit]:
    """Search the knowledge base, blending semantic and lexical signals.

    The function is declared ``async`` so callers can ``await`` it
    uniformly alongside the other (genuinely async) tools in the agent
    graph; the underlying work is CPU-bound and runs synchronously.

    Args:
        query: The user's search query.
        top_k: Maximum number of hits to return. Values ``<= 0`` short-
            circuit to an empty list.

    Returns:
        Up to ``top_k`` :class:`SearchHit` instances ordered by descending
        score. Returns an empty list when the index is empty, the query
        is empty, or the embedding model is unavailable.
    """
    if top_k <= 0 or not query.strip():
        return []

    index = _ensure_index()
    if not index:
        return []

    query_vec = _embed_query(query)
    if query_vec is None:
        return []

    # Stack embeddings once per call. The cost (a few MB copy) is small
    # compared to the network round-trips upstream.
    matrix: NDArray[np.float32] = np.vstack(
        [doc["embedding"] for doc in index]
    )
    cos_scores: NDArray[np.float32] = matrix @ query_vec

    candidate_count = min(len(index), max(top_k * _CANDIDATE_MULTIPLIER, top_k))
    # ``argpartition`` is O(n); we only need the top-N, not a full sort.
    top_idx = np.argpartition(-cos_scores, candidate_count - 1)[:candidate_count]

    query_chars = _cjk_charset(query)

    scored: list[SearchHit] = []
    for i in top_idx:
        idx = int(i)
        cosine = float(cos_scores[idx])
        jaccard = _jaccard(query_chars, _cjk_charset(index[idx]["text"]))
        blended = _COSINE_WEIGHT * cosine + _JACCARD_WEIGHT * jaccard
        scored.append(
            SearchHit(
                text=index[idx]["text"],
                source=index[idx]["source"],
                score=blended,
            )
        )

    scored.sort(key=lambda hit: hit.score, reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Public API — legacy synchronous helper
#
# The older code paths (graphrag_query.graphrag_search / .vector_search)
# import ``search`` and expect a list of plain dicts with ``source`` /
# ``section`` / ``text`` / ``score`` keys. Implementing it on top of the
# same blended scoring keeps the two surfaces in sync.
# ---------------------------------------------------------------------------
def search(
    query: str,
    top_k: int = 3,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Synchronous compatibility wrapper around the hybrid search.

    Args:
        query: The user's search query.
        top_k: Maximum number of hits to return.
        min_score: Drop hits with a final score below this threshold.

    Returns:
        A list of dicts with keys ``source``, ``section``, ``text``,
        ``score``. ``section`` is provided for API compatibility and is
        derived from the source filename.
    """
    if top_k <= 0 or not query.strip():
        return []

    index = _ensure_index()
    if not index:
        return []

    query_vec = _embed_query(query)
    if query_vec is None:
        return []

    matrix: NDArray[np.float32] = np.vstack(
        [doc["embedding"] for doc in index]
    )
    cos_scores: NDArray[np.float32] = matrix @ query_vec

    candidate_count = min(len(index), max(top_k * _CANDIDATE_MULTIPLIER, top_k))
    top_idx = np.argpartition(-cos_scores, candidate_count - 1)[:candidate_count]
    query_chars = _cjk_charset(query)

    rows: list[dict[str, Any]] = []
    for i in top_idx:
        idx = int(i)
        cosine = float(cos_scores[idx])
        jaccard = _jaccard(query_chars, _cjk_charset(index[idx]["text"]))
        blended = _COSINE_WEIGHT * cosine + _JACCARD_WEIGHT * jaccard
        if blended < min_score:
            continue
        source = index[idx]["source"]
        section = Path(source).stem
        rows.append(
            {
                "source": source,
                "section": section,
                "text": index[idx]["text"][:500],
                "score": round(blended, 4),
            }
        )

    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows[:top_k]


def reload() -> list[Document]:
    """Force a full rebuild of the index on the next access.

    Returns:
        The freshly built index.
    """
    global _index
    _index = None
    return _ensure_index()


__all__ = [
    "Document",
    "SearchHit",
    "hybrid_search",
    "reload",
    "search",
]
