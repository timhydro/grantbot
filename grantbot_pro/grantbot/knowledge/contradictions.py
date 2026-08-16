from __future__ import annotations

from grantbot.knowledge.repository import (
    get_fact,
)


def compare_candidate(
    fact_key: str,
    candidate_value: str,
) -> dict:

    existing = get_fact(
        fact_key
    )

    if not existing:
        return {
            "conflict": False,
            "reason": None,
            "existing": None,
        }

    old = (
        existing.get("value")
        or ""
    ).strip()

    new = (
        candidate_value
        or ""
    ).strip()

    if not old or not new:
        return {
            "conflict": False,
            "reason": None,
            "existing": existing,
        }

    conflict = (
        old.casefold()
        != new.casefold()
    )

    return {
        "conflict": conflict,
        "reason":
            "Candidate value differs "
            "from existing organization fact."
            if conflict
            else None,
        "existing": existing,
    }


def contradiction_report(
    candidates: dict[str, str],
) -> list[dict]:

    conflicts = []

    for key, value in candidates.items():
        result = compare_candidate(
            key,
            value,
        )

        if result["conflict"]:
            conflicts.append({
                "fact_key": key,
                "candidate": value,
                "existing":
                    result["existing"],
                "reason":
                    result["reason"],
            })

    return conflicts
