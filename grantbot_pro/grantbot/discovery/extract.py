from __future__ import annotations

import re

from datetime import datetime
from typing import Iterable

from grantbot.core.utils import (
    normalize_text,
)


FUNDING_MARKERS = (
    "grant",
    "funding",
    "fund",
    "request for proposals",
    "request for applications",
    "rfa",
    "rfp",
    "notice of funding",
    "nofo",
    "application",
    "applicants",
    "award",
    "opportunity",
    "sponsorship",
    "community investment",
    "impact investment",
    "program related investment",
    "recoverable grant",
)


MISSION_MARKERS = (
    "reentry",
    "returning citizen",
    "incarceration",
    "justice involved",
    "homeless",
    "homelessness",
    "housing",
    "affordable housing",
    "supportive housing",
    "workforce",
    "job training",
    "employment",
    "community development",
    "economic mobility",
    "poverty",
    "capital",
    "construction",
)


DATE_PATTERNS = (
    r"(?:deadline|due date|application deadline|closing date)"
    r"\s*(?:is|:|-)?\s*"
    r"([A-Z][a-z]+ \d{1,2},? \d{4})",

    r"(?:deadline|due date|application deadline|closing date)"
    r"\s*(?:is|:|-)?\s*"
    r"(\d{1,2}/\d{1,2}/\d{2,4})",

    r"(?:deadline|due date|application deadline|closing date)"
    r"\s*(?:is|:|-)?\s*"
    r"(\d{4}-\d{2}-\d{2})",
)


MONEY_PATTERN = re.compile(
    r"\$\s*"
    r"([0-9]{1,3}"
    r"(?:,[0-9]{3})*"
    r"(?:\.[0-9]{1,2})?)"
)


def funding_relevance(
    text: str,
    query: str = "",
) -> int:

    text_lower = (
        normalize_text(
            text
        ).lower()
    )

    query_lower = (
        normalize_text(
            query
        ).lower()
    )

    score = 0

    for marker in FUNDING_MARKERS:

        if marker in text_lower:
            score += 3

    for marker in MISSION_MARKERS:

        if marker in text_lower:
            score += 2

    if query_lower:

        if query_lower in text_lower:
            score += 8

        else:
            tokens = [
                token
                for token in re.findall(
                    r"[a-z0-9]+",
                    query_lower,
                )
                if len(token) >= 4
            ]

            matches = sum(
                1
                for token in tokens
                if token in text_lower
            )

            score += min(
                matches,
                6,
            )

    return score


def extract_deadline(
    text: str,
) -> str | None:

    text = normalize_text(
        text
    )

    for pattern in DATE_PATTERNS:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(
                1
            )

    return None


def extract_amounts(
    text: str,
) -> list[float]:

    amounts = []

    for match in MONEY_PATTERN.finditer(
        text
    ):

        try:
            amount = float(
                match.group(
                    1
                ).replace(
                    ",",
                    "",
                )
            )

        except ValueError:
            continue

        amounts.append(
            amount
        )

    return amounts


def extract_award_range(
    text: str,
) -> tuple[
    float | None,
    float | None,
]:

    amounts = extract_amounts(
        text
    )

    if not amounts:
        return (
            None,
            None,
        )

    return (
        min(amounts),
        max(amounts),
    )


def extract_eligibility_snippet(
    text: str,
) -> str | None:

    clean = normalize_text(
        text
    )

    patterns = (
        r"eligible applicants?.{0,500}",
        r"eligibility.{0,500}",
        r"who may apply.{0,500}",
        r"applicant eligibility.{0,500}",
    )

    for pattern in patterns:

        match = re.search(
            pattern,
            clean,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(
                0
            )[:600]

    return None
