from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from grantbot.knowledge.canonical import current_facts


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
TRUST = {
    "APPROVED": 1.30,
    "VERIFIED": 1.22,
    "UNVERIFIED": 0.82,
    "MISSING": 0.25,
}


def _tokens(value: Any) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(value or ""))]


def _document(fact: dict[str, Any]) -> str:
    return " ".join(
        (
            str(fact.get("category", "")),
            str(fact.get("fact_key", "")),
            str(fact.get("value", "")),
            str(fact.get("notes", "")),
        )
    )


def rank_facts(
    query: str,
    *,
    limit: int = 20,
    include_unverified: bool = True,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    facts = current_facts(
        verification_states=(
            ["APPROVED", "VERIFIED", "UNVERIFIED"]
            if include_unverified
            else ["APPROVED", "VERIFIED"]
        )
    )
    if not facts:
        return []
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    docs = [_tokens(_document(fact)) for fact in facts]
    document_frequency: Counter[str] = Counter()
    for tokens in docs:
        document_frequency.update(set(tokens))
    n_docs = len(docs)
    avg_len = sum(len(tokens) for tokens in docs) / max(n_docs, 1)
    k1 = 1.5
    b = 0.75
    ranked: list[tuple[float, dict[str, Any]]] = []
    query_phrase = query.strip().casefold()
    for fact, tokens in zip(facts, docs):
        counts = Counter(tokens)
        score = 0.0
        for token in query_tokens:
            tf = counts[token]
            if not tf:
                continue
            df = document_frequency[token]
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            denom = tf + k1 * (1 - b + b * len(tokens) / max(avg_len, 1))
            score += idf * (tf * (k1 + 1) / denom)
        haystack = _document(fact).casefold()
        if query_phrase and query_phrase in haystack:
            score += 3.0
        state = str(fact.get("verification_state", "UNVERIFIED"))
        score *= TRUST.get(state, 0.7)
        score *= 0.75 + 0.25 * float(fact.get("confidence", 0.5))
        if score > 0:
            item = dict(fact)
            item["retrieval_score"] = round(score, 5)
            ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[: max(1, min(limit, 100))]]
