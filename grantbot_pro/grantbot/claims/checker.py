from __future__ import annotations

import re
from collections import Counter
from typing import Any


SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
NUMBER_RE = re.compile(r"(?<![\w])\$?\d[\d,]*(?:\.\d+)?%?(?![\w])")

PROJECTION_TERMS = {
    "plan", "planned", "proposed", "projected", "target", "targeted",
    "anticipate", "anticipated", "intend", "intended", "expect", "expected",
    "will", "would", "could", "upon award", "following award",
}


def _tokens(text: str) -> Counter[str]:
    return Counter(token.lower() for token in TOKEN_RE.findall(text))


def _similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    overlap = sum((a & b).values())
    return overlap / max(sum(a.values()), 1)


def _fact_value(fact: dict[str, Any]) -> str:
    value = fact.get("value", fact.get("answer", ""))
    return str(value or "").strip()


def _number_set(text: str) -> set[str]:
    return {match.replace(",", "").lower() for match in NUMBER_RE.findall(text)}


def _projection_language(sentence: str) -> bool:
    lower = sentence.lower()
    return any(term in lower for term in PROJECTION_TERMS)


def check_claims(
    text: str,
    facts: list[dict[str, Any]],
    *,
    minimum_support: float = 0.12,
) -> dict[str, Any]:
    sentences = [item.strip() for item in SENTENCE_RE.split(text.strip()) if item.strip()]
    fact_numbers: set[str] = set()
    for fact in facts:
        fact_numbers.update(_number_set(_fact_value(fact)))

    checks: list[dict[str, Any]] = []
    unsafe_count = 0
    for sentence in sentences:
        ranked = sorted(
            (
                (_similarity(sentence, _fact_value(fact)), fact)
                for fact in facts
                if _fact_value(fact)
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        best_score = ranked[0][0] if ranked else 0.0
        supporting = [
            {
                "id": fact.get("id"),
                "key": fact.get("fact_key", fact.get("key")),
                "status": str(fact.get("status", "")).upper(),
                "score": round(score, 4),
            }
            for score, fact in ranked[:3]
            if score >= minimum_support
        ]

        sentence_numbers = _number_set(sentence)
        unsupported_numbers = sorted(sentence_numbers - fact_numbers)
        projection_support = any(
            item["status"] == "DRAFT"
            for item in supporting
        )
        projection_violation = projection_support and not _projection_language(sentence)

        issues: list[str] = []
        if unsupported_numbers:
            issues.append("unsupported numeric claim: " + ", ".join(unsupported_numbers))
        if not supporting and len(_tokens(sentence)) >= 4:
            issues.append("no supporting organizational fact retrieved")
        if projection_violation:
            issues.append("planning fact written without prospective language")

        safe = not issues
        if not safe:
            unsafe_count += 1
        checks.append(
            {
                "sentence": sentence,
                "safe": safe,
                "support_score": round(best_score, 4),
                "supporting_facts": supporting,
                "unsupported_numbers": unsupported_numbers,
                "issues": issues,
            }
        )

    return {
        "safe": unsafe_count == 0,
        "sentence_count": len(sentences),
        "unsafe_sentence_count": unsafe_count,
        "checks": checks,
    }
