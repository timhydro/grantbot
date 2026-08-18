from __future__ import annotations

import uuid

from grantbot.knowledge.canonical import current_facts, migrate_legacy_facts, set_fact
from grantbot.knowledge.integrity_v23 import knowledge_status, prepare_canonical_knowledge
from grantbot.knowledge.repository import save_fact
from grantbot.writer import application_writer_v18


def _current(key: str):
    return next((row for row in current_facts() if row["fact_key"] == key), None)


def test_legacy_migration_cannot_replace_stronger_canonical_value() -> None:
    key = f"authority_preserve_{uuid.uuid4().hex}"
    set_fact(
        category="test",
        fact_key=key,
        value="Canonical verified value",
        fact_type="VERIFIED_FACT",
        verification_state="VERIFIED",
        source="canonical-test",
        source_type="test",
        actor="test",
    )
    save_fact(
        category="test",
        fact_key=key,
        value="Legacy approved value",
        status="APPROVED",
        source="legacy-test",
        confidence=1.0,
    )

    result = migrate_legacy_facts()
    current = _current(key)
    assert current is not None
    assert current["value"] == "Canonical verified value"
    assert current["verification_state"] == "VERIFIED"
    assert result["preserved"] >= 1


def test_legacy_migration_can_upgrade_same_value_to_higher_trust() -> None:
    key = f"authority_upgrade_{uuid.uuid4().hex}"
    set_fact(
        category="test",
        fact_key=key,
        value="Shared value",
        fact_type="REASONABLE_PROJECTION",
        verification_state="UNVERIFIED",
        source="canonical-planning",
        source_type="test",
        actor="test",
    )
    save_fact(
        category="test",
        fact_key=key,
        value="Shared value",
        status="APPROVED",
        source="legacy-approved",
        confidence=1.0,
    )

    result = migrate_legacy_facts()
    current = _current(key)
    assert current is not None
    assert current["value"] == "Shared value"
    assert current["verification_state"] == "APPROVED"
    assert result["migrated"] >= 1


def test_prepare_canonical_knowledge_seeds_before_safe_legacy_migration() -> None:
    result = prepare_canonical_knowledge(actor="test-authority")
    assert "seed" in result
    assert "legacy_migration" in result
    assert "profile_conflicts" in result
    assert "active_conflicts" in result

    legal_name = _current("legal_name")
    assert legal_name is not None
    assert legal_name["verification_state"] in {"APPROVED", "VERIFIED"}


def test_knowledge_status_exposes_integrity() -> None:
    prepare_canonical_knowledge(actor="test-authority")
    status = knowledge_status()
    assert "integrity" in status
    assert "profile_conflicts" in status["integrity"]
    assert "active_conflicts" in status["integrity"]


def test_writer_prepares_canonical_knowledge_before_ranking(monkeypatch) -> None:
    calls: list[str] = []

    def fake_prepare(*, actor: str):
        calls.append(actor)
        return {}

    monkeypatch.setattr(application_writer_v18, "prepare_canonical_knowledge", fake_prepare)
    monkeypatch.setattr(application_writer_v18, "rank_facts", lambda *args, **kwargs: [])

    result = application_writer_v18._relevant_facts("Describe the program model")
    assert result == []
    assert calls == ["application-writer-v18"]
