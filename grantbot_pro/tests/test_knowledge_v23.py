from __future__ import annotations

import uuid

from grantbot.app import app
from grantbot.knowledge import profile_v23
from grantbot.knowledge.canonical import current_facts, set_fact


def _current(key: str):
    return next((row for row in current_facts() if row["fact_key"] == key), None)


def test_known_profile_answers_existing_question_bank_facts() -> None:
    profile_v23.seed_known_profile(actor="test-v23")
    statuses = {row.fact_key: row for row in profile_v23.question_statuses()}

    assert statuses["legal_name"].state == "ANSWERED"
    assert statuses["eligibility_requirements"].state == "ANSWERED"
    assert statuses["sam"].state == "ANSWERED"
    assert statuses["sam"].matched_fact_key == "sam_registration"
    assert statuses["grants_gov"].state == "ANSWERED"
    assert statuses["program_model"].state == "PLANNING_CONTEXT"

    pending = {row["fact_key"] for row in profile_v23.next_questions(limit=200)}
    assert "legal_name" not in pending
    assert "sam" not in pending
    assert "grants_gov" not in pending
    assert "program_model" in pending


def test_grant_safe_profile_excludes_planning_context() -> None:
    profile_v23.seed_known_profile(actor="test-v23")
    safe = profile_v23.grant_safe_profile()
    assert safe["legal_name"]["verification_state"] == "VERIFIED"
    assert "eligibility_requirements" in safe
    assert "program_model" not in safe


def test_seed_preserves_conflicting_equal_or_higher_trust_fact(monkeypatch) -> None:
    key = f"test_conflict_{uuid.uuid4().hex}"
    set_fact(
        category="test",
        fact_key=key,
        value="Existing verified value",
        fact_type="VERIFIED_FACT",
        verification_state="VERIFIED",
        source="test-existing",
        source_type="test",
        actor="test",
    )
    candidate = {
        "category": "test",
        "fact_key": key,
        "value": "Different candidate value",
        "fact_type": "USER_PROVIDED_FACT",
        "verification_state": "APPROVED",
        "source": "test-candidate",
        "source_type": "test",
        "confidence": 1.0,
        "notes": "",
    }
    monkeypatch.setattr(profile_v23, "KNOWN_PROFILE", (candidate,))

    result = profile_v23.seed_known_profile(actor="test-conflict")
    assert result["conflicts"][0]["action"] == "PRESERVED_EXISTING"
    current = _current(key)
    assert current is not None
    assert current["value"] == "Existing verified value"
    assert current["verification_state"] == "VERIFIED"


def test_seed_upgrades_same_value_when_candidate_has_more_trust(monkeypatch) -> None:
    key = f"test_upgrade_{uuid.uuid4().hex}"
    set_fact(
        category="test",
        fact_key=key,
        value="Same value",
        fact_type="REASONABLE_PROJECTION",
        verification_state="UNVERIFIED",
        source="test-planning",
        source_type="test",
        actor="test",
    )
    candidate = {
        "category": "test",
        "fact_key": key,
        "value": "Same value",
        "fact_type": "USER_PROVIDED_FACT",
        "verification_state": "APPROVED",
        "source": "test-approved",
        "source_type": "test",
        "confidence": 1.0,
        "notes": "",
    }
    monkeypatch.setattr(profile_v23, "KNOWN_PROFILE", (candidate,))

    result = profile_v23.seed_known_profile(actor="test-upgrade")
    assert result["upgraded"] == 1
    current = _current(key)
    assert current is not None
    assert current["value"] == "Same value"
    assert current["verification_state"] == "APPROVED"


def test_readiness_prioritizes_consequential_missing_information() -> None:
    profile_v23.seed_known_profile(actor="test-v23")
    summary = profile_v23.readiness_summary()
    assert 0 <= summary["readiness_score"] <= 100
    assert summary["question_bank_size"] >= 120
    assert summary["answered"] > 0
    questions = summary["next_questions"]
    assert questions
    assert any(row["requires_confirmation"] for row in questions)


def test_v23_knowledge_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/v23/knowledge/status" in paths
    assert "/v23/knowledge/questions" in paths
    assert "/v23/knowledge/profile" in paths
    assert "/v23/knowledge/seed" in paths
