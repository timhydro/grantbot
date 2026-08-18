from __future__ import annotations

import json
from typing import Any

from grantbot.knowledge.canonical import conflicts as active_conflicts
from grantbot.knowledge.canonical import current_facts, migrate_legacy_facts
from grantbot.knowledge.profile_v23 import KNOWN_PROFILE, TRUST_RANK, readiness_summary, seed_known_profile


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def profile_conflicts() -> list[dict[str, Any]]:
    current = {str(row["fact_key"]): row for row in current_facts()}
    output: list[dict[str, Any]] = []
    for expected in KNOWN_PROFILE:
        key = str(expected["fact_key"])
        actual = current.get(key)
        if actual is None:
            continue
        actual_value = actual.get("value")
        expected_value = expected.get("value")
        if _stable(actual_value) == _stable(expected_value):
            continue
        actual_state = str(actual.get("verification_state", "MISSING")).upper()
        expected_state = str(expected.get("verification_state", "MISSING")).upper()
        output.append(
            {
                "fact_key": key,
                "current_value": actual_value,
                "current_state": actual_state,
                "current_source": actual.get("source"),
                "profile_value": expected_value,
                "profile_state": expected_state,
                "current_trust_rank": TRUST_RANK.get(actual_state, 0),
                "profile_trust_rank": TRUST_RANK.get(expected_state, 0),
                "action": "REVIEW_CURRENT_VS_PROFILE",
            }
        )
    return output


def prepare_canonical_knowledge(*, actor: str = "knowledge-authority-v23.1") -> dict[str, Any]:
    seed = seed_known_profile(actor=actor)
    migration = migrate_legacy_facts()
    return {
        "seed": seed,
        "legacy_migration": migration,
        "profile_conflicts": profile_conflicts(),
        "active_conflicts": active_conflicts(),
    }


def knowledge_status() -> dict[str, Any]:
    payload = readiness_summary()
    payload["integrity"] = {
        "profile_conflicts": profile_conflicts(),
        "active_conflicts": active_conflicts(),
    }
    return payload
