from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from grantbot.command_center.service import (
    application_portfolio,
    award_portfolio,
    deadline_portfolio,
    portfolio_risks,
    portfolio_summary,
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
    prefix="/master/command-center",
    tags=["GrantBot Executive Command Center"],
)

READ_ROLES = (
    ADMIN,
    AUTHORIZED_REPRESENTATIVE,
    FINANCIAL_REVIEWER,
    GRANT_WRITER,
    REVIEWER,
)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(
        status_code=500,
        detail=f"{type(exc).__name__}: {exc}",
    )


@router.get("/summary")
def summary(
    as_of: str | None = Query(default=None, max_length=10),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return portfolio_summary(as_of=as_of)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/applications")
def applications(
    as_of: str | None = Query(default=None, max_length=10),
    limit: int = Query(default=200, ge=1, le=1000),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return application_portfolio(as_of=as_of, limit=limit)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/awards")
def awards(
    as_of: str | None = Query(default=None, max_length=10),
    limit: int = Query(default=200, ge=1, le=1000),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return award_portfolio(as_of=as_of, limit=limit)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/deadlines")
def deadlines(
    as_of: str | None = Query(default=None, max_length=10),
    days: int = Query(default=90, ge=0, le=3650),
    include_past_due: bool = Query(default=True),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return deadline_portfolio(
            as_of=as_of,
            days=days,
            include_past_due=include_past_due,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/risks")
def risks(
    as_of: str | None = Query(default=None, max_length=10),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return portfolio_risks(as_of=as_of)
    except Exception as exc:
        raise _translate(exc) from exc
