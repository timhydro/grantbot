from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.budget.engine import calculate_budget
from grantbot.master.service import health, learning_profile, submission_gate, system_versions
from grantbot.outcomes.logic_model import validate_logic_model


router = APIRouter(prefix="/master", tags=["GrantBot Unified Master"])


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


@router.get("/health")
def master_health() -> dict[str, Any]:
    return health()


@router.get("/system/versions")
def versions() -> dict[str, Any]:
    return system_versions()


@router.get("/workspaces/{workspace_id}/gate")
def gate(workspace_id: str) -> dict[str, Any]:
    try:
        return submission_gate(workspace_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/budget/calculate")
def budget(payload: BudgetRequest) -> dict[str, Any]:
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
def logic_model(payload: LogicModelRequest) -> dict[str, Any]:
    return validate_logic_model(payload.model)


@router.get("/learning/profile")
def profile() -> dict[str, Any]:
    return learning_profile()
