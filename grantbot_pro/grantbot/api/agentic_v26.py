from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.agents.crewai_local import crewai_status, kickoff_local_grant_crew
from grantbot.agents.pipeline_v26 import AGENT_ROLES, build_execution_plan, write_and_plan
from grantbot.agents.research_v26 import build_evidence_brief
from grantbot.eligibility.tax_status import TaxStatus
from grantbot.funding.live_runner import run_live_discovery
from grantbot.matching.competitive_v14 import analyze_competitiveness


router = APIRouter(prefix="/v26/agents", tags=["GrantBot Agentic Pipeline v26"])


class OpportunityPayload(BaseModel):
    title: str = ""
    funder: str = ""
    agency: str = ""
    description: str = ""
    eligibility: str = ""
    deadline: str | None = None
    source_url: str = ""
    opportunity_type: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanRequest(BaseModel):
    opportunity: OpportunityPayload
    facts: list[dict[str, Any]] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    writing_quality: dict[str, Any] | None = None


class WritePlanRequest(PlanRequest):
    question: str = Field(min_length=1)
    section: str = "general"
    priorities: list[str] = Field(default_factory=list)
    max_words: int | None = Field(default=None, ge=1, le=10000)


class CrewRequest(BaseModel):
    dossier: str = Field(min_length=1, max_length=100000)
    question: str = Field(min_length=1, max_length=10000)
    max_words: int | None = Field(default=None, ge=1, le=10000)
    model: str | None = None


class DiscoveryRequest(BaseModel):
    state: str = Field(default="Florida", min_length=2, max_length=100)
    counties: list[str] = Field(default_factory=lambda: ["Escambia"], max_length=25)
    cities: list[str] = Field(default_factory=lambda: ["Pensacola"], max_length=25)
    lanes: list[str] | None = None
    max_terms_per_lane: int = Field(default=2, ge=1, le=10)
    per_query_limit: int = Field(default=10, ge=1, le=100)
    maximum_queries: int = Field(default=40, ge=1, le=1000)
    minimum_review_score: int = Field(default=60, ge=0, le=100)
    applicant_tax_status: TaxStatus = TaxStatus.PENDING_501C3
    has_fiscal_sponsor: bool = False
    create_review_folders: bool = False


class MatchRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=80)
    acquire_if_missing: bool = True


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": 26,
        "mode": "local-first-human-gated",
        "roles": list(AGENT_ROLES),
        "crewai": crewai_status().to_dict(),
        "safe_to_submit": False,
    }


@router.post("/research")
def research(payload: PlanRequest) -> dict[str, Any]:
    brief = build_evidence_brief(
        opportunity=payload.opportunity.model_dump(),
        facts=payload.facts,
    )
    return {
        "version": 26,
        "agent": "evidence_research",
        "brief": brief.to_dict(),
        "safe_to_submit": False,
    }


@router.post("/match")
def match(payload: MatchRequest) -> dict[str, Any]:
    try:
        result = analyze_competitiveness(
            payload.opportunity_id,
            acquire_if_missing=payload.acquire_if_missing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "version": 26,
        "agent": "grant_strategy",
        "matching": result.to_dict(),
        "safe_to_submit": False,
    }


@router.post("/plan")
def plan(payload: PlanRequest) -> dict[str, Any]:
    return build_execution_plan(
        opportunity=payload.opportunity.model_dump(),
        facts=payload.facts,
        requirements=payload.requirements,
        writing_quality=payload.writing_quality,
    ).to_dict()


@router.post("/write-and-plan")
def write_plan(payload: WritePlanRequest) -> dict[str, Any]:
    try:
        return write_and_plan(
            opportunity=payload.opportunity.model_dump(),
            question=payload.question,
            section=payload.section,
            facts=payload.facts,
            priorities=payload.priorities,
            requirements=payload.requirements,
            max_words=payload.max_words,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 503, detail=str(exc)) from exc


@router.post("/crew")
def crew(payload: CrewRequest) -> dict[str, Any]:
    status = crewai_status()
    if not status.installed:
        raise HTTPException(
            status_code=503,
            detail="CrewAI optional dependencies are not installed. Install GrantBot with: pip install -e '.[agents]'",
        )
    if not status.ollama_available:
        raise HTTPException(status_code=503, detail=status.error or "Local Ollama is unavailable")
    try:
        output = kickoff_local_grant_crew(
            dossier=payload.dossier,
            question=payload.question,
            max_words=payload.max_words,
            model=payload.model,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 503, detail=str(exc)) from exc
    return {
        "status": "READY_FOR_HUMAN_REVIEW",
        "output": output,
        "provider": "local-ollama",
        "safe_to_submit": False,
    }


@router.post("/discover")
def discover(payload: DiscoveryRequest) -> dict[str, Any]:
    try:
        result = run_live_discovery(
            state=payload.state,
            counties=payload.counties,
            cities=payload.cities,
            lanes=payload.lanes,
            max_terms_per_lane=payload.max_terms_per_lane,
            per_query_limit=payload.per_query_limit,
            maximum_queries=payload.maximum_queries,
            minimum_review_score=payload.minimum_review_score,
            applicant_tax_status=payload.applicant_tax_status,
            has_fiscal_sponsor=payload.has_fiscal_sponsor,
            create_review_folders=payload.create_review_folders,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "version": 26,
        "agent": "funding_intelligence",
        "result": result.to_dict(),
        "safe_to_submit": False,
    }
