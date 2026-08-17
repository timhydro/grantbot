from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from grantbot.review.staging_v17 import (
    create_workspace,
    get_workspace,
    health,
    list_workspaces,
    resolve_risk,
    save_draft,
    transition_workspace,
    update_checklist_item,
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
    prefix="/v17/staging",
    tags=["GrantBot Human Review Staging v17"],
)

READ_ROLES = (
    ADMIN,
    GRANT_WRITER,
    REVIEWER,
    FINANCIAL_REVIEWER,
    AUTHORIZED_REPRESENTATIVE,
)


class CreateWorkspaceRequest(BaseModel):
    manual_urls: list[str] = Field(default_factory=list, max_length=25)
    refresh_analysis: bool = False


class ProvenanceItem(BaseModel):
    source: str = Field(min_length=1, max_length=500)
    note: str = Field(default="", max_length=1000)


class DraftUpdateRequest(BaseModel):
    response: str = Field(default="", max_length=100000)
    status: str = Field(default="DRAFT", min_length=1, max_length=40)
    provenance: list[ProvenanceItem] = Field(default_factory=list, max_length=100)


class ChecklistUpdateRequest(BaseModel):
    status: str = Field(min_length=1, max_length=40)
    actor: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=5000)


class RiskResolutionRequest(BaseModel):
    actor: str = Field(default="", max_length=200)
    resolution_note: str = Field(min_length=1, max_length=5000)


class TransitionRequest(BaseModel):
    target_stage: str = Field(min_length=1, max_length=50)
    actor: str = Field(default="", max_length=200)
    note: str = Field(min_length=1, max_length=5000)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.get("/health")
def staging_health() -> dict[str, Any]:
    return health()


@router.get("")
def staging_list(
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    return list_workspaces()


@router.post("/create/{opportunity_id}")
def staging_create(
    opportunity_id: str,
    payload: CreateWorkspaceRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    del principal
    try:
        return create_workspace(
            opportunity_id,
            manual_urls=payload.manual_urls,
            refresh_analysis=payload.refresh_analysis,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/{workspace_id}")
def staging_get(
    workspace_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return get_workspace(workspace_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.put("/{workspace_id}/drafts/{task_id}")
def staging_save_draft(
    workspace_id: str,
    task_id: str,
    payload: DraftUpdateRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    try:
        provenance = [item.model_dump() for item in payload.provenance]
        provenance.append(
            {
                "source": f"authenticated:{principal.key_id}",
                "note": f"Saved by {principal.actor}",
            }
        )
        return save_draft(
            workspace_id,
            task_id,
            response=payload.response,
            status=payload.status,
            provenance=provenance,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.put("/{workspace_id}/checklist/{checklist_id}")
def staging_checklist(
    workspace_id: str,
    checklist_id: str,
    payload: ChecklistUpdateRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    try:
        return update_checklist_item(
            workspace_id,
            checklist_id,
            status=payload.status,
            actor=principal.actor,
            note=payload.note,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/{workspace_id}/risks/{risk_id}/resolve")
def staging_resolve_risk(
    workspace_id: str,
    risk_id: str,
    payload: RiskResolutionRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    try:
        return resolve_risk(
            workspace_id,
            risk_id,
            actor=principal.actor,
            resolution_note=payload.resolution_note,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/{workspace_id}/transition")
def staging_transition(
    workspace_id: str,
    payload: TransitionRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, REVIEWER, AUTHORIZED_REPRESENTATIVE)
    ),
) -> dict[str, Any]:
    target = payload.target_stage.strip().upper()
    if target in {"APPROVED", "READY_FOR_SUBMISSION", "SUBMITTED"} and principal.role not in {
        ADMIN,
        AUTHORIZED_REPRESENTATIVE,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only ADMIN or AUTHORIZED_REPRESENTATIVE may approve an application "
                "or advance it to submission readiness."
            ),
        )
    if target == "SUBMITTED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Direct SUBMITTED transition is disabled. Final submission requires a separate authorized action.",
        )
    try:
        return transition_workspace(
            workspace_id,
            target_stage=target,
            actor=principal.actor,
            note=payload.note,
        )
    except Exception as exc:
        raise _translate(exc) from exc
