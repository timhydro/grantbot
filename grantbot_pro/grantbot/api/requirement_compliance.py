from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from grantbot.compliance.requirements import (
    requirement_summary,
    set_requirement_status,
    sync_requirements,
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
    prefix="/master/requirements",
    tags=["GrantBot Authoritative Requirement Compliance"],
)

READ_ROLES = (
    ADMIN,
    GRANT_WRITER,
    REVIEWER,
    FINANCIAL_REVIEWER,
    AUTHORIZED_REPRESENTATIVE,
)


class RequirementStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=40)
    evidence_note: str = Field(min_length=1, max_length=5000)
    evidence_source: str = Field(min_length=1, max_length=2000)


def _error(exc: Exception) -> HTTPException:
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


@router.post("/sync/{workspace_id}")
def sync_workspace_requirements(
    workspace_id: str,
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, REVIEWER)
    ),
) -> dict[str, Any]:
    try:
        return sync_requirements(
            workspace_id,
            actor=principal.actor,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/status/{workspace_id}")
def get_workspace_requirement_status(
    workspace_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return requirement_summary(workspace_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.put("/status/{workspace_id}/{requirement_id}")
def review_requirement(
    workspace_id: str,
    requirement_id: str,
    payload: RequirementStatusRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, REVIEWER, AUTHORIZED_REPRESENTATIVE)
    ),
) -> dict[str, Any]:
    try:
        return set_requirement_status(
            workspace_id,
            requirement_id,
            status=payload.status,
            actor=principal.actor,
            evidence_note=payload.evidence_note,
            evidence_source=payload.evidence_source,
            allow_not_applicable=True,
        )
    except Exception as exc:
        raise _error(exc) from exc
