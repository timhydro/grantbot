from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from grantbot.agents.adversarial_panel_v30 import panel_status, run_adversarial_panel
from grantbot.intelligence.adaptive_v30 import (
    analyze_strategic_decision,
    consistency_audit,
    funder_profile,
    intelligence_status,
    model_performance,
    record_funder_event,
    record_model_run,
    save_approved_learning,
    score_opportunity,
    sentence_provenance,
)
from grantbot.knowledge.canonical import current_facts
from grantbot.security.auth import ADMIN, GRANT_WRITER, REVIEWER, Principal, require_roles


router = APIRouter(prefix="/v30/intelligence", tags=["GrantBot Adaptive Intelligence v30"])


class OpportunityScoreRequest(BaseModel):
    award_amount: float = Field(ge=0)
    win_probability: float = Field(ge=0, le=1)
    estimated_hours: float = Field(gt=0)
    strategic_fit: float = Field(ge=0, le=100)
    eligibility_confidence: float = Field(ge=0, le=100)
    award_value_score: float = Field(ge=0, le=100)
    application_effort_score: float = Field(ge=0, le=100)
    deadline_feasibility: float = Field(ge=0, le=100)
    organizational_readiness: float = Field(ge=0, le=100)
    hard_blockers: list[str] = Field(default_factory=list, max_length=100)


class StrategicDecisionRequest(OpportunityScoreRequest):
    win_probability_low: float = Field(ge=0, le=1)
    win_probability_high: float = Field(ge=0, le=1)
    hourly_cost: float = Field(default=0, ge=0)
    evidence_confidence: float = Field(ge=0, le=100)
    risk_tolerance: float = Field(default=0.5, ge=0, le=1)
    alternative_expected_value: float = Field(default=0, ge=0)


class ModelRunRequest(BaseModel):
    role: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=300)
    task_type: str = Field(min_length=1, max_length=100)
    success: bool
    quality_score: float | None = Field(default=None, ge=0, le=100)
    hallucination_rate: float | None = Field(default=None, ge=0, le=1)
    latency_ms: float | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    human_accepted: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FunderEventRequest(BaseModel):
    funder_key: str = Field(min_length=1, max_length=200)
    funder_name: str = Field(min_length=1, max_length=300)
    event_type: str = Field(min_length=1, max_length=100)
    human_approved: bool
    opportunity_id: str | None = Field(default=None, max_length=300)
    outcome: str | None = Field(default=None, max_length=100)
    amount_requested: float | None = Field(default=None, ge=0)
    amount_awarded: float | None = Field(default=None, ge=0)
    reviewer_score: float | None = Field(default=None, ge=0, le=100)
    feedback: str = Field(default="", max_length=100000)
    attributes: dict[str, Any] = Field(default_factory=dict)


class LearningRequest(BaseModel):
    artifact_key: str = Field(min_length=1, max_length=300)
    section_type: str = Field(min_length=1, max_length=100)
    funder_archetype: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=300000)
    approved_by: str = Field(min_length=1, max_length=200)
    reviewer_score: float | None = Field(default=None, ge=0, le=100)
    outcome: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    human_approved: bool


class ProvenanceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=300000)
    minimum_overlap: float = Field(default=0.28, gt=0, le=1)


class ConsistencyRequest(BaseModel):
    narrative: str = Field(min_length=1, max_length=300000)
    budget: dict[str, float]
    workplan: dict[str, Any]
    expected_total: float | None = Field(default=None, ge=0)
    tolerance: float = Field(default=0.01, ge=0)


class PanelRequest(BaseModel):
    dossier: str = Field(min_length=1, max_length=300000)
    final_answer: str = Field(min_length=1, max_length=300000)
    budget_context: dict[str, Any] = Field(default_factory=dict)


@router.get("/status")
def status(
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    result = intelligence_status()
    result["adversarial_panel"] = panel_status()
    return result


@router.post("/opportunity-score")
def opportunity_score(
    payload: OpportunityScoreRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    return score_opportunity(**payload.model_dump()).to_dict()


@router.post("/strategic-decision")
def strategic_decision(
    payload: StrategicDecisionRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    """Return an explainable, uncertainty-aware pursuit recommendation."""
    del principal
    try:
        return analyze_strategic_decision(**payload.model_dump()).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/model-runs")
def create_model_run(
    payload: ModelRunRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        record_id = record_model_run(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": record_id, "recorded": True}


@router.get("/model-performance")
def get_model_performance(
    role: str | None = None,
    task_type: str | None = None,
    min_samples: int = 1,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        results = model_performance(role=role, task_type=task_type, min_samples=min_samples)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"results": results, "count": len(results)}


@router.post("/funder-events")
def create_funder_event(
    payload: FunderEventRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        record_id = record_funder_event(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": record_id, "recorded": True}


@router.get("/funders/{funder_key}")
def get_funder_profile(
    funder_key: str,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        return funder_profile(funder_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/approved-learning")
def create_approved_learning(
    payload: LearningRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        record_id = save_approved_learning(**payload.model_dump())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": record_id, "recorded": True, "human_approved": True}


@router.post("/provenance")
def provenance(
    payload: ProvenanceRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    facts = current_facts(verification_states=["VERIFIED", "APPROVED"])
    supports = sentence_provenance(
        text=payload.text,
        facts=facts,
        minimum_overlap=payload.minimum_overlap,
    )
    items = [support.to_dict() for support in supports]
    unresolved = [item for item in items if item["support_status"] in {"UNSUPPORTED", "UNRESOLVED", "PARTIAL"}]
    return {
        "sentences": items,
        "sentence_count": len(items),
        "unresolved_count": len(unresolved),
        "all_supported": not unresolved,
    }


@router.post("/consistency")
def consistency(
    payload: ConsistencyRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        issues = consistency_audit(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    items = [issue.to_dict() for issue in issues]
    blockers = [item for item in items if item["severity"] == "BLOCKER"]
    warnings = [item for item in items if item["severity"] == "WARNING"]
    return {
        "issues": items,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "consistent": not blockers,
    }


@router.post("/adversarial-panel")
def adversarial_panel(
    payload: PanelRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        return run_adversarial_panel(**payload.model_dump()).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
