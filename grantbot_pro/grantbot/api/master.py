from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from grantbot.budget.engine import calculate_budget
from grantbot.evidence.repository import ingest_document, list_requirements
from grantbot.knowledge.canonical import current_facts, set_fact
from grantbot.master.service import health, learning_profile, submission_gate, system_versions
from grantbot.outcomes.logic_model import validate_logic_model
from grantbot.retrieval.hybrid import rank_facts
from grantbot.security.auth import (
    ADMIN,
    AUTHORIZED_REPRESENTATIVE,
    FINANCIAL_REVIEWER,
    GRANT_WRITER,
    REVIEWER,
    Principal,
    create_api_key,
    list_api_keys,
    require_roles,
    revoke_api_key,
    security_status,
)


router = APIRouter(prefix="/master", tags=["GrantBot Unified Master"])

READ_ROLES = (
    ADMIN,
    GRANT_WRITER,
    REVIEWER,
    FINANCIAL_REVIEWER,
    AUTHORIZED_REPRESENTATIVE,
)


class BudgetItem(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    quantity: float = Field(default=1, ge=0)
    unit_cost: float = Field(ge=0)
    months: float = Field(default=1, ge=0)


class BudgetRequest(BaseModel):
    items: list[BudgetItem] = Field(min_length=1, max_length=500)
    indirect_rate_percent: float = Field(default=0, ge=0, le=100)
    indirect_base_categories: list[str] = Field(default_factory=list, max_length=100)
    cash_match: float = Field(default=0, ge=0)
    in_kind_match: float = Field(default=0, ge=0)
    participant_count: int | None = Field(default=None, ge=1)
    housing_unit_count: int | None = Field(default=None, ge=1)


class LogicModelRequest(BaseModel):
    model: dict[str, Any]


class CanonicalFactRequest(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    fact_key: str = Field(min_length=1, max_length=200)
    value: Any = None
    fact_type: str = Field(min_length=1, max_length=50)
    verification_state: str = Field(min_length=1, max_length=50)
    source: str = Field(default="", max_length=1000)
    source_type: str = Field(default="", max_length=100)
    confidence: float = Field(default=1.0, ge=0, le=1)
    notes: str = Field(default="", max_length=5000)
    actor: str = Field(default="", max_length=200)


class DocumentRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    pages: list[str] = Field(min_length=1, max_length=1000)
    source_url: str = Field(default="", max_length=2000)
    document_type: str = Field(default="", max_length=200)
    authority_type: str = Field(default="AUTO", max_length=50)


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=5000)
    limit: int = Field(default=20, ge=1, le=100)
    include_unverified: bool = True


class CreateKeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=50)


@router.get("/health")
def master_health() -> dict[str, Any]:
    return health()


@router.get("/system/versions")
def versions() -> dict[str, Any]:
    return system_versions()


@router.get("/workspaces/{workspace_id}/gate")
def gate(
    workspace_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return submission_gate(workspace_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/budget/calculate")
def budget(
    payload: BudgetRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, FINANCIAL_REVIEWER)
    ),
) -> dict[str, Any]:
    del principal
    try:
        return calculate_budget(
            items=[item.model_dump() for item in payload.items],
            indirect_rate_percent=payload.indirect_rate_percent,
            indirect_base_categories=payload.indirect_base_categories or None,
            cash_match=payload.cash_match,
            in_kind_match=payload.in_kind_match,
            participant_count=payload.participant_count,
            housing_unit_count=payload.housing_unit_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/logic-model/validate")
def logic_model(
    payload: LogicModelRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    return validate_logic_model(payload.model)


@router.get("/learning/profile")
def profile(
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    del principal
    return learning_profile()


@router.post("/facts")
def create_canonical_fact(
    payload: CanonicalFactRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    try:
        data = payload.model_dump()
        data["actor"] = principal.actor
        return set_fact(**data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/facts")
def list_canonical_facts(
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    return current_facts()


@router.post("/documents/analyze")
def analyze_document(
    payload: DocumentRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    del principal
    try:
        return ingest_document(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/requirements")
def requirements(
    opportunity_id: str,
    authoritative_only: bool = True,
    category: str | None = None,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    try:
        return list_requirements(
            opportunity_id=opportunity_id,
            authoritative_only=authoritative_only,
            category=category,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/retrieval/facts")
def retrieve_facts(
    payload: RetrievalRequest,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    return rank_facts(
        payload.query,
        limit=payload.limit,
        include_unverified=payload.include_unverified,
    )


@router.get("/security/status")
def get_security_status(
    principal: Principal = Depends(require_roles(ADMIN)),
) -> dict[str, Any]:
    del principal
    return security_status()


@router.get("/security/keys")
def get_security_keys(
    principal: Principal = Depends(require_roles(ADMIN)),
) -> list[dict[str, Any]]:
    del principal
    return list_api_keys()


@router.post("/security/keys")
def issue_security_key(
    payload: CreateKeyRequest,
    principal: Principal = Depends(require_roles(ADMIN)),
) -> dict[str, Any]:
    del principal
    try:
        return create_api_key(label=payload.label, role=payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/security/keys/{key_id}")
def revoke_security_key(
    key_id: str,
    principal: Principal = Depends(require_roles(ADMIN)),
) -> dict[str, Any]:
    try:
        return revoke_api_key(key_id, actor=principal)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
