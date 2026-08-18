from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


NUMBER_RE = re.compile(r"(?<!\w)\$?\d[\d,]*(?:\.\d+)?%?(?!\w)")


@dataclass(frozen=True, slots=True)
class QualityResult:
    passed: bool
    score: int
    word_count: int
    issues: list[str]
    unsupported_numbers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    if unsupported:
        score -= min(45, 15 * len(unsupported))
        issues.append("Unsupported numeric claims: " + ", ".join(unsupported))

    if max_words is not None and wc > max_words:
        score -= 25
        issues.append(f"Word limit exceeded: {wc}/{max_words}")

    missing_terms = [
        t
        for t in (required_terms or [])
        if t.strip() and t.lower() not in text.lower()
    ]
    if missing_terms:
        score -= min(25, 5 * len(missing_terms))
        issues.append("Missing funder priorities: " + ", ".join(missing_terms))

    if not any(
        token in text.lower()
        for token in re.findall(r"[a-zA-Z]{4,}", question.lower())
    ):
        score -= 15
        issues.append("Draft may not directly answer the question")

    score = max(0, min(100, score))
    return QualityResult(
        passed=score >= 80 and not unsupported,
        score=score,
        word_count=wc,
        issues=issues,
        unsupported_numbers=unsupported,
    )
