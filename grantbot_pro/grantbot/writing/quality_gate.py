from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


NUMBER_RE = re.compile(r"(?<!\w)\$?\d[\d,]*(?:\.\d+)?%?(?!\w)")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
EVIDENCE_RE = re.compile(
    r"\b(?:according to|data|evidence|report|study|survey|documented|verified|measured|tracked|evaluated|baseline|outcome|result)\b",
    re.IGNORECASE,
)
STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "also",
    "and",
    "are",
    "because",
    "been",
    "being",
    "between",
    "both",
    "can",
    "could",
    "does",
    "for",
    "from",
    "have",
    "how",
    "into",
    "its",
    "more",
    "most",
    "our",
    "program",
    "project",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "through",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "will",
    "with",
    "would",
    "your",
}


@dataclass(frozen=True, slots=True)
class QualityResult:
    passed: bool
    score: int
    word_count: int
    issues: list[str]
    unsupported_numbers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _question_terms(question: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for token in WORD_RE.findall(question.lower()):
        if token in STOPWORDS or len(token) < 4 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def _relevance_ratio(question: str, draft: str) -> float:
    terms = _question_terms(question)
    if not terms:
        return 1.0
    text = draft.lower()
    hits = sum(1 for term in terms if term in text)
    return hits / len(terms)


def evaluate_draft(
    *,
    question: str,
    draft: str,
    facts: list[dict[str, Any]],
    max_words: int | None = None,
    required_terms: list[str] | None = None,
) -> QualityResult:
    text = draft.strip()
    if not text:
        return QualityResult(False, 0, 0, ["Draft is empty"], [])

    source = " ".join(
        str(f.get("value", f.get("answer", "")))
        for f in facts
        if f.get("value", f.get("answer")) not in (None, "", [], {})
    ).lower()

    unsupported = sorted(
        {
            n
            for n in NUMBER_RE.findall(text)
            if n.lower() not in source
        }
    )

    score = 100
    issues: list[str] = []
    wc = len(text.split())
    hard_blockers: list[str] = []

    if unsupported:
        score -= min(45, 15 * len(unsupported))
        issues.append("Unsupported numeric claims: " + ", ".join(unsupported))
        hard_blockers.append("unsupported_numbers")

    if max_words is not None and wc > max_words:
        score -= 25
        issues.append(f"Word limit exceeded: {wc}/{max_words}")
        hard_blockers.append("word_limit")

    if wc < 25:
        score -= 15
        issues.append("Draft is too brief to demonstrate sufficient specificity")
        if wc < 10:
            hard_blockers.append("too_brief")

    missing_terms = [
        t
        for t in (required_terms or [])
        if t.strip() and t.lower() not in text.lower()
    ]
    if missing_terms:
        score -= min(25, 5 * len(missing_terms))
        issues.append("Missing funder priorities: " + ", ".join(missing_terms))

    relevance = _relevance_ratio(question, text)
    if relevance < 0.34:
        score -= 20
        issues.append("Draft may not directly cover enough of the funder's question")
        hard_blockers.append("off_question")
    elif relevance < 0.5:
        score -= 10
        issues.append("Draft only partially covers the funder's question")

    has_structure = any(mark in text for mark in (".", ";", ":", "\n"))
    if not has_structure and wc >= 25:
        score -= 8
        issues.append("Draft lacks clear sentence or paragraph structure")

    factual_source_present = bool(source.strip())
    evidence_signal = bool(EVIDENCE_RE.search(text)) or bool(NUMBER_RE.search(text))
    if factual_source_present and wc >= 60 and not evidence_signal:
        score -= 8
        issues.append("Draft would benefit from clearer evidence, measurement, or verified factual support")

    score = max(0, min(100, score))
    return QualityResult(
        passed=score >= 80 and not hard_blockers,
        score=score,
        word_count=wc,
        issues=issues,
        unsupported_numbers=unsupported,
    )
