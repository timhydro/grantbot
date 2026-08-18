from __future__ import annotations

from grantbot.app import app
from grantbot.discovery.rerank_v22 import rerank_payload, score_opportunity


def test_reentry_workforce_opportunity_ranks_high() -> None:
    result = score_opportunity(
        title="Reentry Workforce Employment Initiative",
        agency="Department of Labor",
        matched_keywords=["reentry", "workforce development"],
    )
    assert result.priority == "HIGH"
    assert result.score >= 50
    assert "reentry" in result.matched_domains
    assert "workforce" in result.matched_domains


def test_continuum_of_care_homelessness_program_ranks_high() -> None:
    result = score_opportunity(
        title=(
            "Continuum of Care Competition and Youth Homelessness "
            "Demonstration Program Grants"
        ),
        agency="Department of Housing and Urban Development",
        matched_keywords=["homelessness", "supportive housing"],
    )
    assert result.priority == "HIGH"
    assert result.score >= 50
    assert "homelessness" in result.matched_domains
    assert "housing" in result.matched_domains


def test_academic_fellowship_is_hard_rejected() -> None:
    result = score_opportunity(
        title="Postdoctoral Research Fellowship in Genomics",
        agency="National Science Foundation",
        matched_keywords=["workforce"],
    )
    assert result.priority == "REJECT"
    assert result.score == 0
    assert result.rejection_reasons


def test_generic_basic_research_program_does_not_float_high() -> None:
    result = score_opportunity(
        title="Advanced Basic Research Program",
        agency="Federal Research Agency",
    )
    assert result.priority == "REJECT"
    assert result.score < 15


def test_rerank_payload_orders_mission_fit_before_generic_results() -> None:
    payload = {
        "items": [
            {
                "opportunity_id": "generic",
                "title": "General Technical Assistance Program",
                "agency": "Agency",
                "matched_keywords": [],
                "assistance_listings": [],
                "analysis_level": "SUMMARY",
                "fit_score": 40,
                "final_score": 40,
                "priority": "HIGH",
                "rejection_reasons": [],
                "strengths": [],
                "weaknesses": [],
                "blockers": [],
            },
            {
                "opportunity_id": "reentry",
                "title": "Reentry Workforce Employment Initiative",
                "agency": "Department of Labor",
                "matched_keywords": ["reentry", "workforce development"],
                "assistance_listings": [],
                "analysis_level": "SUMMARY",
                "fit_score": 20,
                "final_score": 20,
                "priority": "MEDIUM",
                "rejection_reasons": [],
                "strengths": [],
                "weaknesses": [],
                "blockers": [],
            },
        ]
    }
    result = rerank_payload(payload)
    assert result["ranking_version"] == "22.0"
    assert result["items"][0]["opportunity_id"] == "reentry"
    assert result["items"][0]["priority"] == "HIGH"
    assert result["items"][1]["priority"] == "REJECT"
    assert result["high_count"] == 1
    assert result["reject_count"] == 1


def test_full_analysis_with_blockers_stays_rejected() -> None:
    payload = {
        "items": [
            {
                "opportunity_id": "blocked",
                "title": "Supportive Housing Initiative",
                "agency": "HUD",
                "matched_keywords": ["supportive housing"],
                "assistance_listings": [],
                "analysis_level": "FULL",
                "fit_score": 90,
                "final_score": 90,
                "priority": "HIGH",
                "rejection_reasons": [],
                "strengths": [],
                "weaknesses": [],
                "blockers": ["Applicant type is ineligible"],
            }
        ]
    }
    result = rerank_payload(payload)
    assert result["items"][0]["priority"] == "REJECT"


def test_v22_queue_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/v22/queue/health" in paths
    assert "/v22/queue/discover" in paths
    assert "/v22/queue/latest" in paths
