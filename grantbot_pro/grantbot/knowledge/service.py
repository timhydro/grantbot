from __future__ import annotations

import json
from collections import Counter

from grantbot.knowledge.question_bank import (
    QUESTIONS,
)
from grantbot.knowledge.repository import (
    approved_facts,
    get_fact,
    missing_facts,
    verified_facts,
    working_facts,
)


CRITICAL_KEYS = {
    "legal_name": 100,
    "ein": 100,
    "tax_exempt_status": 100,
    "annual_budget": 95,
    "sam_registration": 95,
    "uei": 95,
    "grants_gov_registration": 95,
    "financial_controls": 90,
    "current_people_served": 90,
    "annual_people_served": 90,
    "eligibility_requirements": 88,
    "program_names": 85,
    "program_descriptions": 85,
    "current_funding": 85,
    "board_members": 82,
    "mailing_address": 80,
}


def knowledge_summary() -> dict:
    working = working_facts()
    verified = verified_facts()
    approved = approved_facts()
    missing = missing_facts()

    categories = Counter(
        row["category"]
        for row in working
    )

    return {
        "total_working_facts":
            len(working),
        "approved":
            len(approved),
        "verified_or_approved":
            len(verified),
        "missing":
            len(missing),
        "categories":
            dict(categories),
        "question_bank_size":
            len(QUESTIONS),
    }


def readiness_score() -> dict:
    missing = missing_facts()

    missing_keys = {
        row["fact_key"]
        for row in missing
    }

    weighted_total = sum(
        CRITICAL_KEYS.values()
    )

    weighted_missing = sum(
        weight
        for key, weight
        in CRITICAL_KEYS.items()
        if key in missing_keys
    )

    if not weighted_total:
        score = 0
    else:
        score = round(
            100
            * (
                1
                - weighted_missing
                / weighted_total
            ),
            1,
        )

    return {
        "score": max(
            0,
            min(100, score),
        ),
        "critical_missing": [
            {
                "fact_key": key,
                "weight": weight,
            }
            for key, weight
            in sorted(
                CRITICAL_KEYS.items(),
                key=lambda item:
                    item[1],
                reverse=True,
            )
            if key in missing_keys
        ],
    }


def next_questions(
    limit: int = 10,
) -> list[dict]:

    missing = {
        row["fact_key"]
        for row in missing_facts()
    }

    results = []

    for q in QUESTIONS:
        candidate_keys = {
            q.key,
        }

        if candidate_keys & missing:
            results.append({
                "category":
                    q.category,
                "fact_key":
                    q.key,
                "question":
                    q.question,
                "priority":
                    q.priority,
            })

    results.sort(
        key=lambda row: (
            row["priority"],
            -CRITICAL_KEYS.get(
                row["fact_key"],
                0,
            ),
            row["category"],
        )
    )

    return results[:limit]


def grant_safe_profile() -> dict:
    facts = verified_facts()

    return {
        row["fact_key"]: {
            "value":
                row["value"],
            "status":
                row["status"],
            "source":
                row["source"],
            "confidence":
                row["confidence"],
        }
        for row in facts
    }


def investor_profile() -> dict:
    categories = {
        "organization",
        "vision",
        "program",
        "impact",
        "finance",
        "investor",
        "funding",
        "evidence",
        "partnerships",
    }

    rows = [
        row
        for row in working_facts()
        if row["category"]
        in categories
    ]

    return {
        "facts": rows,
        "missing_investor_information": [
            row
            for row in missing_facts()
            if row["category"]
            in {
                "investor",
                "finance",
                "evidence",
            }
        ],
    }
