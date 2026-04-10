"""Lightweight similarity search for agent memory.

Provides TF-IDF-based semantic similarity without external dependencies.
Used as an optional enhancement over FTS5 keyword matching for memory
recall when more nuanced matching is needed.
"""

from __future__ import annotations

import math
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, stripping punctuation."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _term_frequency(tokens: list[str]) -> dict[str, float]:
    """Compute term frequency (TF) for a list of tokens."""
    counts = Counter(tokens)
    total = len(tokens)
    if total == 0:
        return {}
    return {term: count / total for term, count in counts.items()}


def _inverse_document_frequency(
    documents: list[list[str]],
) -> dict[str, float]:
    """Compute inverse document frequency (IDF) across documents."""
    n_docs = len(documents)
    if n_docs == 0:
        return {}

    doc_freq: Counter[str] = Counter()
    for doc_tokens in documents:
        unique_terms = set(doc_tokens)
        for term in unique_terms:
            doc_freq[term] += 1

    return {
        term: math.log((1 + n_docs) / (1 + df)) + 1
        for term, df in doc_freq.items()
    }


def _tfidf_vector(
    tf: dict[str, float],
    idf: dict[str, float],
) -> dict[str, float]:
    """Compute TF-IDF vector for a document."""
    return {term: freq * idf.get(term, 1.0) for term, freq in tf.items()}


def _cosine_similarity(
    vec_a: dict[str, float],
    vec_b: dict[str, float],
) -> float:
    """Compute cosine similarity between two sparse vectors."""
    if not vec_a or not vec_b:
        return 0.0

    # Dot product
    common_terms = set(vec_a.keys()) & set(vec_b.keys())
    dot = sum(vec_a[t] * vec_b[t] for t in common_terms)

    # Magnitudes
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


def similarity_search(
    query: str,
    documents: list[str],
    *,
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[tuple[int, float]]:
    """Rank documents by TF-IDF cosine similarity to a query.

    Uses a lightweight TF-IDF approach that requires no external
    dependencies (no numpy, no scikit-learn, no vector databases).

    Args:
        query: The search query text.
        documents: List of document texts to search.
        top_k: Maximum number of results to return.
        min_score: Minimum similarity score threshold (0.0-1.0).

    Returns:
        List of (document_index, similarity_score) tuples, sorted by
        score descending.
    """
    if not query or not documents:
        return []

    # Tokenize everything
    query_tokens = _tokenize(query)
    doc_tokens_list = [_tokenize(doc) for doc in documents]

    if not query_tokens:
        return []

    # Build IDF from all documents + query
    all_docs = doc_tokens_list + [query_tokens]
    idf = _inverse_document_frequency(all_docs)

    # Build query vector
    query_tf = _term_frequency(query_tokens)
    query_vec = _tfidf_vector(query_tf, idf)

    # Score each document
    scored: list[tuple[int, float]] = []
    for i, doc_tokens in enumerate(doc_tokens_list):
        if not doc_tokens:
            continue
        doc_tf = _term_frequency(doc_tokens)
        doc_vec = _tfidf_vector(doc_tf, idf)
        score = _cosine_similarity(query_vec, doc_vec)
        if score > min_score:
            scored.append((i, score))

    # Sort by score descending, limit to top_k
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
