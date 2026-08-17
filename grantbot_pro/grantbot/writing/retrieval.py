from __future__ import annotations

from typing import Any, List

try:
    from sentence_transformers import SentenceTransformer
    import faiss
    _HAS_SIF = True
except Exception:  # pragma: no cover - optional deps
    _HAS_SIF = False

import math
import re

# Simple tokenizer for fallback
_WORD_RE = re.compile(r"\w+")


def _keyword_score(query: str, text: str) -> float:
    q_tokens = set(w.lower() for w in _WORD_RE.findall(query) if len(w) > 2)
    t_tokens = set(w.lower() for w in _WORD_RE.findall(text) if len(w) > 2)
    if not q_tokens or not t_tokens:
        return 0.0
    overlap = q_tokens & t_tokens
    return len(overlap) / math.sqrt(len(t_tokens) or 1)


def select_relevant_facts(context_query: str, facts: List[dict[str, Any]], k: int = 8) -> List[dict[str, Any]]:
    """Select top-k relevant fact objects (from facts list) for the given context_query.

    facts: list of dicts expected to have at least 'value' and optionally 'id'.
    This function tries to use sentence-transformers + faiss if available, otherwise falls back to keyword scoring.
    """
    if not facts:
        return []

    # prefer semantic retrieval when available
    if _HAS_SIF:
        try:
            # instantiate a shared model (lightweight) and compute embeddings on the fly
            model = SentenceTransformer("all-MiniLM-L6-v2")
            texts = [str(f.get("value") or "") for f in facts]
            embs = model.encode(texts, convert_to_numpy=True)
            qv = model.encode([context_query], convert_to_numpy=True)
            # normalize
            import numpy as _np

            def _normalize(v):
                norms = (_np.linalg.norm(v, axis=1, keepdims=True) + 1e-12)
                return v / norms

            embs = _normalize(embs)
            qv = _normalize(qv)
            # cosine similarity
            sims = (embs @ qv.T).squeeze(axis=1)
            idxs = list(range(len(facts)))
            ranked = sorted(idxs, key=lambda i: float(sims[i]), reverse=True)
            selected = [facts[i] for i in ranked[:k]]
            return selected
        except Exception:
            # fall back to keyword
            pass

    # simple keyword overlap scoring
    scored = []
    for f in facts:
        text = str(f.get("value") or "")
        score = _keyword_score(context_query, text)
        scored.append((score, f))
    scored.sort(key=lambda t: t[0], reverse=True)
    selected = [f for s, f in scored[:k] if s > 0]
    # if no positive scores, return top k items defensively
    if not selected:
        return [f for _, f in scored[:k]]
    return selected
