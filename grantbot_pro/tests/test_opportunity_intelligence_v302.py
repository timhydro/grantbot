from __future__ import annotations

from pathlib import Path

import pytest

from grantbot.automation.opportunity_pipeline import (
    Opportunity,
    analyze_opportunity,
    rank_opportunities,
)
from grantbot.intelligence.opportunity_v302 import (
    assess_eligibility,
    learned_opportunity_signal,
    record_opportunity_adjudication,
    source_completeness,
)


def test_smart_reentry_is_partner_only_for_nonprofit() -> None:
    result = analyze_opportunity(
        Opportunity(
            id="363588",
            title="BJA FY 2026 Smart Reentry Demonstration Program",
            funder="Bureau of Justice Assistance",
            description="Supports collaborative reentry strategies.",
            eligibility=(
                "State governments; county governments; city or township governments; "
                "special district governments; tribal governments"
            ),
            deadline="2099-09-24",
            source_url="https://www.grants.gov/example",
        ),
        use_learning=False,
    )
    assert result["priority"] == "PARTNER_ONLY"
    assert not result["hard_reject"]
    assert not result["eligibility_decision"]["direct_applicant_allowed"]
    assert result["eligibility_decision"]["partner_route_available"]
    assert result["readiness_score"] <= 25


def test_nih_clinical_research_false_positive_is_rejected() -> None:
    result = analyze_opportunity(
        Opportunity(
            id="357658",
            title=(
                "Limited Competition: Small Grant Program for the NCATS Clinical "
                "and Translational Science Award (R03 Clinical Trial Optional)"
            ),
            funder="National Institutes of Health",
            description="Research may discuss housing and reentry as social determinants.",
            eligibility="Institutions of higher education",
            deadline="2099-10-19",
            source_url="https://www.grants.gov/example",
        ),
        use_learning=False,
    )
    assert result["hard_reject"]
    assert result["priority"] == "REJECT"
    assert result["score"] == 0
    assert "clinical_or_biomedical_research" in result["eligibility_decision"]["negative_domains"]


def test_nonprofit_explicitly_allowed_proceeds_directly() -> None:
    result = assess_eligibility(
        title="Family-Based Reentry Treatment",
        funder="Bureau of Justice Assistance",
        eligibility="Nonprofits with or without 501(c)(3) and faith-based organizations",
    )
    assert result.decision == "DIRECT"
    assert result.direct_applicant_allowed


def test_federal_readiness_is_capped_without_full_nofo() -> None:
    result = source_completeness(
        title="Federal Reentry Grant",
        funder="Bureau of Justice Assistance",
        source_url="https://www.grants.gov/example",
        eligibility="Nonprofit organizations",
        nofo_text="short synopsis",
        extracted_questions=[],
        extracted_requirements=[],
    )
    assert result["readiness_cap"] == 25
    assert not result["complete_for_drafting"]
    assert "full federal NOFO text" in result["missing"]


def test_drafting_is_blocked_when_authoritative_sources_are_incomplete() -> None:
    with pytest.raises(RuntimeError, match="authoritative source acquisition"):
        analyze_opportunity(
            Opportunity(
                id="federal-direct",
                title="Federal Reentry Employment Program",
                funder="Bureau of Justice Assistance",
                description="Funds reentry employment and workforce development.",
                eligibility="Nonprofit and faith-based organizations",
                deadline="2099-09-24",
                source_url="https://www.grants.gov/example",
            ),
            generate_drafts=True,
            use_learning=False,
        )


def test_opportunity_learning_requires_human_approval(tmp_path: Path) -> None:
    db = tmp_path / "learning.sqlite3"
    with pytest.raises(PermissionError):
        record_opportunity_adjudication(
            opportunity_id="opp-1",
            title="Reentry Employment Grant",
            funder="Example Foundation",
            decision="PURSUE",
            rationale="Strong fit",
            reviewer="reviewer",
            human_approved=False,
            db_path=db,
        )


def test_human_adjudication_creates_bounded_soft_signal(tmp_path: Path) -> None:
    db = tmp_path / "learning.sqlite3"
    record_opportunity_adjudication(
        opportunity_id="opp-1",
        title="Florida Reentry Employment and Workforce Grant",
        funder="Example Foundation",
        decision="PURSUE",
        rationale="Direct mission and applicant fit confirmed",
        reviewer="authorized-reviewer",
        human_approved=True,
        db_path=db,
    )
    signal = learned_opportunity_signal(
        title="Florida Reentry Workforce Opportunity",
        funder="Example Foundation",
        db_path=db,
    )
    assert signal["sample_count"] == 1
    assert 0 < signal["score_adjustment"] <= 10
    assert "hard gates remain authoritative" in signal["policy"]


def test_learning_cannot_override_hard_eligibility_rejection(tmp_path: Path) -> None:
    db = tmp_path / "learning.sqlite3"
    record_opportunity_adjudication(
        opportunity_id="bad-history",
        title="NCATS Clinical and Translational Science Award",
        funder="National Institutes of Health",
        decision="PURSUE",
        rationale="Historical test record",
        reviewer="authorized-reviewer",
        human_approved=True,
        db_path=db,
    )
    gate = assess_eligibility(
        title="NCATS Clinical and Translational Science Award Clinical Trial",
        funder="National Institutes of Health",
        eligibility="Institutions of higher education",
    )
    signal = learned_opportunity_signal(
        title="NCATS Clinical and Translational Science Award Clinical Trial",
        funder="National Institutes of Health",
        db_path=db,
    )
    assert signal["score_adjustment"] > 0
    assert gate.decision == "REJECT"


def test_direct_opportunity_ranks_above_higher_scoring_partner_only_route() -> None:
    results = rank_opportunities(
        [
            Opportunity(
                id="partner",
                title="Smart Reentry Demonstration",
                funder="Bureau of Justice Assistance",
                description="Reentry housing workforce employment supportive services",
                eligibility="State governments and county governments",
                deadline="2099-09-24",
                source_url="https://www.grants.gov/partner",
            ),
            Opportunity(
                id="direct",
                title="Community Reentry Workforce Grant",
                funder="Example Foundation",
                description="Reentry employment and workforce development",
                eligibility="Nonprofit and faith-based organizations",
                deadline="2099-09-24",
                source_url="https://example.org/direct",
            ),
        ],
        generate_drafts=False,
    )
    assert results[0]["id"] == "direct"
    assert results[1]["priority"] == "PARTNER_ONLY"
