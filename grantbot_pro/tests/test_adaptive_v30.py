from __future__ import annotations

from pathlib import Path

import pytest

from grantbot.agents.crewai_multimodel import _candidate_models, ai_policy
from grantbot.intelligence.adaptive_v30 import (
    analyze_strategic_decision,
    consistency_audit,
    funder_profile,
    model_performance,
    record_funder_event,
    record_model_run,
    save_approved_learning,
    score_opportunity,
    sentence_provenance,
)


def test_cloud_first_policy_is_default() -> None:
    assert ai_policy({}) == "cloud_first"


def test_invalid_ai_policy_is_rejected() -> None:
    with pytest.raises(ValueError):
        ai_policy({"GRANTBOT_AI_POLICY": "anything_goes"})


def test_cloud_first_candidate_order_prefers_role_cloud_model() -> None:
    env = {
        "GRANTBOT_AI_POLICY": "cloud_first",
        "GRANTBOT_ALLOW_METERED_AI": "1",
        "GEMINI_API_KEY": "test-key",
        "MISTRAL_API_KEY": "test-key",
        "GRANTBOT_CREWAI_MODEL": "ollama/llama3.2:3b",
    }
    candidates = _candidate_models("writing", env)
    assert candidates[0] == "mistral/mistral-large-latest"
    assert "ollama/llama3.2:3b" in candidates


def test_explicit_role_model_overrides_policy() -> None:
    env = {
        "GRANTBOT_AI_POLICY": "cloud_first",
        "GRANTBOT_CREWAI_WRITING_MODEL": "ollama/custom:latest",
        "GRANTBOT_ALLOW_METERED_AI": "1",
        "MISTRAL_API_KEY": "test-key",
    }
    assert _candidate_models("writing", env) == ["ollama/custom:latest"]


def test_opportunity_value_scoring_and_expected_value() -> None:
    result = score_opportunity(
        award_amount=500_000,
        win_probability=0.22,
        estimated_hours=25,
        strategic_fit=95,
        eligibility_confidence=92,
        award_value_score=95,
        application_effort_score=80,
        deadline_feasibility=90,
        organizational_readiness=85,
    )
    assert result.expected_funding_value == 110_000
    assert result.expected_value_per_hour == 4_400
    assert result.score >= 80
    assert result.pursuit_priority in {"APPLY", "PRIORITIZE"}


def test_hard_blocker_forces_hold() -> None:
    result = score_opportunity(
        award_amount=1_000_000,
        win_probability=0.9,
        estimated_hours=10,
        strategic_fit=100,
        eligibility_confidence=100,
        award_value_score=100,
        application_effort_score=100,
        deadline_feasibility=100,
        organizational_readiness=100,
        hard_blockers=["Applicant type is ineligible"],
    )
    assert result.pursuit_priority == "HOLD"
    assert result.score < 25


def test_strategic_decision_exposes_uncertainty_and_questions() -> None:
    result = analyze_strategic_decision(
        award_amount=500_000,
        win_probability=0.30,
        win_probability_low=0.10,
        win_probability_high=0.50,
        estimated_hours=100,
        hourly_cost=75,
        strategic_fit=90,
        eligibility_confidence=85,
        award_value_score=90,
        application_effort_score=70,
        deadline_feasibility=80,
        organizational_readiness=80,
        evidence_confidence=60,
        risk_tolerance=0.25,
        alternative_expected_value=20_000,
    )
    assert result.expected_value_range == {"low": 42_500, "base": 142_500, "high": 242_500}
    assert result.risk_adjusted_score < result.base_score
    assert result.confidence == pytest.approx(0.4)
    assert any("narrow" in question for question in result.questions_to_resolve)
    assert result.human_review_required is True


def test_strategic_decision_rejects_incoherent_probability_range() -> None:
    with pytest.raises(ValueError, match="ordered"):
        analyze_strategic_decision(
            award_amount=100_000, win_probability=0.4,
            win_probability_low=0.5, win_probability_high=0.6,
            estimated_hours=10, hourly_cost=50, strategic_fit=80,
            eligibility_confidence=80, award_value_score=80,
            application_effort_score=80, deadline_feasibility=80,
            organizational_readiness=80, evidence_confidence=80,
        )


def test_model_telemetry_ranks_successful_high_quality_model(tmp_path: Path) -> None:
    db = tmp_path / "adaptive.sqlite3"
    record_model_run(
        role="writing",
        provider="mistral",
        model="mistral/mistral-large-latest",
        task_type="narrative",
        success=True,
        quality_score=96,
        hallucination_rate=0.01,
        latency_ms=900,
        cost_usd=0.04,
        human_accepted=True,
        db_path=db,
    )
    record_model_run(
        role="writing",
        provider="other",
        model="other/weaker",
        task_type="narrative",
        success=False,
        quality_score=55,
        hallucination_rate=0.20,
        latency_ms=300,
        cost_usd=0.01,
        human_accepted=False,
        db_path=db,
    )
    ranked = model_performance(role="writing", task_type="narrative", db_path=db)
    assert ranked[0]["model"] == "mistral/mistral-large-latest"
    assert ranked[0]["performance_score"] > ranked[1]["performance_score"]


def test_funder_memory_uses_only_human_approved_events_for_outcome_metrics(tmp_path: Path) -> None:
    db = tmp_path / "adaptive.sqlite3"
    record_funder_event(
        funder_key="example-foundation",
        funder_name="Example Foundation",
        event_type="OUTCOME",
        human_approved=True,
        outcome="AWARDED",
        amount_requested=100_000,
        amount_awarded=80_000,
        reviewer_score=92,
        feedback="Strong implementation plan",
        attributes={"priority": "workforce"},
        db_path=db,
    )
    record_funder_event(
        funder_key="example-foundation",
        funder_name="Example Foundation",
        event_type="OUTCOME",
        human_approved=False,
        outcome="DECLINED",
        amount_requested=900_000,
        feedback="AI-generated unconfirmed event",
        db_path=db,
    )
    profile = funder_profile("example-foundation", db_path=db)
    assert profile["events"] == 2
    assert profile["approved_events"] == 1
    assert profile["wins"] == 1
    assert profile["win_rate"] == 1.0
    assert profile["requested_total"] == 100_000
    assert profile["awarded_total"] == 80_000
    assert profile["attributes"]["priority"] == "workforce"


def test_learning_rejects_non_human_approved_content(tmp_path: Path) -> None:
    db = tmp_path / "adaptive.sqlite3"
    with pytest.raises(PermissionError):
        save_approved_learning(
            artifact_key="draft-1",
            section_type="need",
            funder_archetype="foundation",
            text="Unreviewed AI draft",
            approved_by="reviewer",
            human_approved=False,
            db_path=db,
        )


def test_learning_accepts_explicit_human_approval(tmp_path: Path) -> None:
    db = tmp_path / "adaptive.sqlite3"
    record_id = save_approved_learning(
        artifact_key="approved-1",
        section_type="need",
        funder_archetype="foundation",
        text="Human-approved final narrative.",
        approved_by="authorized-reviewer",
        reviewer_score=94,
        outcome="submitted",
        human_approved=True,
        db_path=db,
    )
    assert record_id > 0


def test_sentence_provenance_supports_matching_verified_fact() -> None:
    facts = [
        {
            "fact_id": "f-1",
            "fact_key": "program_model",
            "verification_state": "VERIFIED",
            "value": "The program combines transitional housing with workforce development.",
            "source": "board-approved-program-plan",
        }
    ]
    result = sentence_provenance(
        text="The program combines transitional housing with workforce development.",
        facts=facts,
    )
    assert len(result) == 1
    assert result[0].support_status == "SUPPORTED"
    assert result[0].supporting_fact_ids == ["f-1"]


def test_sentence_provenance_flags_unsupported_number() -> None:
    facts = [
        {
            "fact_id": "f-1",
            "verification_state": "APPROVED",
            "value": "The program plans transitional housing.",
            "source": "program-plan",
        }
    ]
    result = sentence_provenance(
        text="The program will house 75 participants.",
        facts=facts,
    )
    assert result[0].support_status in {"UNSUPPORTED", "PARTIAL"}
    assert "75" in result[0].unsupported_numbers


def test_consistency_audit_finds_budget_total_mismatch() -> None:
    issues = consistency_audit(
        narrative="Personnel and transportation support the work plan.",
        budget={"personnel": 50_000, "transportation": 10_000},
        workplan={"participants": 30},
        expected_total=70_000,
    )
    assert any(issue.code == "BUDGET_TOTAL_MISMATCH" and issue.severity == "BLOCKER" for issue in issues)


def test_consistency_audit_accepts_matching_budget_total() -> None:
    issues = consistency_audit(
        narrative="Personnel and transportation support 30 participants.",
        budget={"personnel": 50_000, "transportation": 10_000},
        workplan={"participants": 30},
        expected_total=60_000,
    )
    assert not any(issue.code == "BUDGET_TOTAL_MISMATCH" for issue in issues)
