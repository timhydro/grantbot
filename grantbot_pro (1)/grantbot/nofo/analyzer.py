from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


DOMAIN_WEIGHTS = {
    "reentry": 35,
    "homelessness": 20,
    "housing": 20,
    "employment": 15,
    "workforce": 15,
    "supportive_services": 10,
}

DOMAIN_TERMS = {
    "reentry": ("reentry", "re-entry", "formerly incarcerated", "justice-involved"),
    "homelessness": ("homelessness", "homeless", "unsheltered"),
    "housing": ("housing", "supportive housing", "transitional housing", "affordable housing"),
    "employment": ("employment", "job placement", "economic opportunity"),
    "workforce": ("workforce", "job training", "skills training", "vocational"),
    "supportive_services": ("supportive services", "case management", "mentoring", "life skills", "transportation"),
}

HARD_REJECT = (
    "postdoctoral applicants only",
    "institutions of higher education only",
    "tribal governments only",
    "state governments only",
    "county governments only",
    "city governments only",
    "individual applicants only",
    "for-profit organizations only",
)


@dataclass(frozen=True, slots=True)
class NofoAnalysis:
    fit_score: int
    priority: str
    hard_reject: bool
    blockers: list[str]
    matched_domains: dict[str, int]
    application_questions: list[str]
    priorities: list[str]
    requirements: list[str]
    writer_handoff: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_questions(text: str) -> list[str]:
    questions: list[str] = []

    numbered = re.compile(
        r"(?:^|\s)(?:\d{1,3}|[A-Z])[\.\)]\s*"
        r"(.+?\?)"
        r"(?=\s+(?:\d{1,3}|[A-Z])[\.\)]\s*|$)",
        re.DOTALL,
    )

    for match in numbered.finditer(text):
        question = " ".join(match.group(1).split()).strip()

        if len(question) >= 8 and question not in questions:
            questions.append(question)

    if questions:
        return questions

    for line in text.splitlines():
        clean = " ".join(line.strip().split())

        if not clean.endswith("?") or len(clean) < 8:
            continue

        clean = re.sub(
            r"^\s*(?:\d{1,3}|[A-Z])[\.\)]\s*",
            "",
            clean,
        )

        if clean not in questions:
            questions.append(clean)

    return questions


def analyze_nofo(
    text: str,
    *,
    title: str = "",
    funder: str = "",
    opportunity_number: str = "",
    organization_missing: list[str] | None = None,
) -> NofoAnalysis:
    if len(text.strip()) < 20:
        raise ValueError("NOFO text is too short")

    lower = " ".join((title, funder, text)).lower()
    blockers = [f"hard eligibility conflict: {term}" for term in HARD_REJECT if term in lower]
    hard = bool(blockers)

    matched: dict[str, int] = {}
    score = 0
    for domain, weight in DOMAIN_WEIGHTS.items():
        if any(term in lower for term in DOMAIN_TERMS[domain]):
            matched[domain] = weight
            score += weight

    if "florida" in lower or "pensacola" in lower or "escambia" in lower:
        score += 5

    if any(term in lower for term in ("nonprofit", "non-profit", "501(c)(3)", "faith-based")):
        score += 5

    if "smart reentry" in lower:
        matched["strong_reentry_bonus"] = 30
        score += 30

    if "bureau of justice assistance" in lower and "reentry" in matched:
        matched["mission_funder_bonus"] = 10
        score += 10

    if "research in the formation of engineers" in title.lower():
        blockers.append("academic/research opportunity outside Broken Growth mission")
        hard = True

    score = 0 if hard else min(100, score)

    if hard:
        priority = "REJECT"
    elif score >= 80:
        priority = "HIGH"
    elif score >= 60:
        priority = "MEDIUM"
    elif score >= 40:
        priority = "LOW"
    else:
        priority = "VERY_LOW"

    questions = _extract_questions(text)
    priorities = []
    for domain, terms in DOMAIN_TERMS.items():
        if any(term in lower for term in terms):
            priorities.append(domain.replace("_", " "))

    requirements = []
    for line in text.splitlines():
        stripped = " ".join(line.split())
        low = stripped.lower()
        if any(x in low for x in ("must submit", "must include", "is required", "are required", "shall ")):
            if stripped and stripped not in requirements:
                requirements.append(stripped)

    handoff = {
        "grant_title": title,
        "funder": funder,
        "opportunity_number": opportunity_number,
        "priorities": priorities,
        "requirements": requirements,
        "questions": questions,
        "fit_score": score,
        "priority": priority,
        "organization_missing": organization_missing or [],
    }

    return NofoAnalysis(
        score,
        priority,
        hard,
        blockers,
        matched,
        questions,
        priorities,
        requirements,
        handoff,
    )
