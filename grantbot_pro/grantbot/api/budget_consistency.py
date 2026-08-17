from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from grantbot.budget.workspace import (
    approve_budget,
    budget_consistency,
    budget_history,
    latest_budget,
    save_workspace_budget,
)
from grantbot.security.auth import (
    ADMIN,
    AUTHORIZED_REPRESENTATIVE,
    FINANCIAL_REVIEWER,
    GRANT_WRITER,
    REVIEWER,
    Principal,
    require_roles,
)


router = APIRouter(
    prefix="/master/budgets",
    tags=["GrantBot Workspace Budget Consistency"],
)

READ_ROLES = (
    ADMIN,
    GRANT_WRITER,
    REVIEWER,
    FINANCIAL_REVIEWER,
    AUTHORIZED_REPRESENTATIVE,
)


class WorkspaceBudgetItem(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    quantity: float = Field(default=1, ge=0)
    unit_cost: float = Field(ge=0)
    months: float = Field(default=1, ge=0)


class WorkspaceBudgetRequest(BaseModel):
    items: list[WorkspaceBudgetItem] = Field(min_length=1, max_length=500)
    indirect_rate_percent: float = Field(default=0, ge=0, le=100)
    indirect_base_categories: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    cash_match: float = Field(default=0, ge=0)
    in_kind_match: float = Field(default=0, ge=0)
    participant_count: int | None = Field(default=None, ge=1)
    housing_unit_count: int | None = Field(default=None, ge=1)


class BudgetApprovalRequest(BaseModel):
    note: str = Field(min_length=1, max_length=5000)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(
        status_code=500,
        detail=f"{type(exc).__name__}: {exc}",
    )


@router.post("/{workspace_id}")
def save_budget(
    workspace_id: str,
    payload: WorkspaceBudgetRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, FINANCIAL_REVIEWER)
    ),
) -> dict[str, Any]:
    try:
        return save_workspace_budget(
            workspace_id,
            items=[item.model_dump() for item in payload.items],
            indirect_rate_percent=payload.indirect_rate_percent,
            indirect_base_categories=(
                payload.indirect_base_categories or None
            ),
            cash_match=payload.cash_match,
            in_kind_match=payload.in_kind_match,
            participant_count=payload.participant_count,
            housing_unit_count=payload.housing_unit_count,
            actor=principal.actor,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/{workspace_id}/latest")
def get_latest_budget(
    workspace_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        value = latest_budget(workspace_id)
        if value is None:
            raise FileNotFoundError(
                f"No budget exists for workspace: {workspace_id}"
            )
        return value
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/{workspace_id}/history")
def get_budget_history(
    workspace_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    try:
        return budget_history(workspace_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/{workspace_id}/consistency")
def get_budget_consistency(
    workspace_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return budget_consistency(workspace_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/{workspace_id}/{budget_id}/approve")
def approve_workspace_budget(
    workspace_id: str,
    budget_id: str,
    payload: BudgetApprovalRequest,
    principal: Principal = Depends(
        require_roles(
            ADMIN,
            FINANCIAL_REVIEWER,
            AUTHORIZED_REPRESENTATIVE,
        )
    ),
) -> dict[str, Any]:
    try:
        return approve_budget(
            workspace_id,
            budget_id,
            actor=principal.actor,
            note=payload.note,
        )
    except Exception as exc:
        raise _translate(exc) from exc
