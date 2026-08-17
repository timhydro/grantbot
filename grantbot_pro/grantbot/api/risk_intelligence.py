from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from grantbot.risk.engine import (
    assess_workspace_risk,
    evaluate_workspace_risk,
    latest_risk,
    risk_history,
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
    prefix="/master/risk",
    tags=["GrantBot Evidence-Calibrated Risk Intelligence"],
)

READ_ROLES = (
    ADMIN,
    GRANT_WRITER,
    REVIEWER,
    FINANCIAL_REVIEWER,
    AUTHORIZED_REPRESENTATIVE,
)


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


@router.get("/{workspace_id}/preview")
def preview_risk(
    workspace_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        result = evaluate_workspace_risk(workspace_id)
        factors = result.get("factors", [])
        result["factors"] = [
            item.to_dict() if hasattr(item, "to_dict") else item
            for item in factors
        ]
        return result
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/{workspace_id}/assess")
def assess_risk(
    workspace_id: str,
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, REVIEWER, AUTHORIZED_REPRESENTATIVE)
    ),
) -> dict[str, Any]:
    try:
        return assess_workspace_risk(
            workspace_id,
            actor=principal.actor,
        ).to_dict()
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/{workspace_id}/latest")
def get_latest_risk(
    workspace_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        result = latest_risk(workspace_id)
        if result is None:
            raise FileNotFoundError(
                f"No risk assessment exists for workspace: {workspace_id}"
            )
        return result
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/{workspace_id}/history")
def get_risk_history(
    workspace_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    try:
        return risk_history(workspace_id)
    except Exception as exc:
        raise _translate(exc) from exc
