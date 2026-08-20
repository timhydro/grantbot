from __future__ import annotations

from grantbot.agents.pipeline_v26 import AGENT_ROLES, build_execution_plan
from grantbot.app import app


def test_v26_agent_roles_cover_full_grant_lifecycle() -> None:
    ids = {item["id"] for item in AGENT_ROLES}
    assert {
        "funding_intelligence",
        "eligibility_compliance",
        "evidence_research",
        "grant_strategy",
        "narrative_writer",
        "quality_reviewer",
        "human_review_router",
    } <= ids


def test_v26_execution_plan_is_human_gated() -> None:
    plan = build_execution_plan(
        opportunity={
            "title": "Reentry Workforce Grant",
            "funder": "Public Agency",
            "description": "Workforce and reentry services for eligible nonprofits.",
            "eligibility": "Eligible nonprofit organizations may apply.",
            "source_url": "https://example.gov/opportunity",
        },
        facts=[
            {
                "key": "program_population",
                "value": "adults returning from incarceration",
                "status": "VERIFIED",
                "source": "organization record",
            }
        ],
        requirements=["Authorized official certification required before submission"],
        writing_quality={"passed": True},
    )
    assert plan.pursuit_status == "READY_FOR_HUMAN_REVIEW"
    assert plan.human_review_required is True
    assert plan.human_review_reasons
    assert plan.next_actions[-1].startswith("Keep final submission")


def test_v26_execution_plan_blocks_missing_source_and_eligibility() -> None:
    plan = build_execution_plan(
        opportunity={"title": "Potential Housing Opportunity"},
        facts=[{"key": "unknown_budget", "value": None, "status": "MISSING"}],
    )
    assert plan.pursuit_status == "BLOCKED"
    assert any("Official source URL" in item for item in plan.blockers)
    assert any("Eligibility language" in item for item in plan.blockers)
    assert plan.missing_fact_count == 1


def test_v26_routes_are_registered_in_openapi() -> None:
    paths = set(app.openapi()["paths"])
    assert "/v26/agents/health" in paths
    assert "/v26/agents/plan" in paths
    assert "/v26/agents/write-and-plan" in paths
    assert "/v26/agents/crew" in paths
    assert "/v26/agents/discover" in paths
