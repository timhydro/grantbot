from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from grantbot.discovery.orchestrator import (
    discovery_health,
    get_campaign,
    plan_discovery_campaign,
    recent_campaigns,
    run_discovery_campaign,
)
from grantbot.discovery.source_health import reset_source
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
    prefix="/master/discovery",
    tags=["GrantBot Multi-Source Funding Discovery"],
)

READ_ROLES = (
    ADMIN,
    GRANT_WRITER,
    REVIEWER,
    FINANCIAL_REVIEWER,
    AUTHORIZED_REPRESENTATIVE,
)


class DiscoveryCampaignRequest(BaseModel):
    state: str = Field(default="Florida", min_length=2, max_length=80)
    counties: list[str] = Field(default_factory=lambda: ["Escambia"], max_length=25)
    cities: list[str] = Field(default_factory=lambda: ["Pensacola"], max_length=25)
    lanes: list[str] = Field(default_factory=list, max_length=25)
    max_queries: int = Field(default=25, ge=1, le=100)
    per_query_limit: int = Field(default=10, ge=1, le=25)
    broad_web: bool = True
    include_conditional: bool = True
    include_investment: bool = True
    include_subscription: bool = False


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


@router.post("/plan")
def plan(
    payload: DiscoveryCampaignRequest,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return plan_discovery_campaign(
            state=payload.state,
            counties=payload.counties,
            cities=payload.cities,
            lanes=payload.lanes or None,
            max_queries=payload.max_queries,
            include_conditional=payload.include_conditional,
            include_investment=payload.include_investment,
            include_subscription=payload.include_subscription,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/run")
def run(
    payload: DiscoveryCampaignRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    try:
        return run_discovery_campaign(
            state=payload.state,
            counties=payload.counties,
            cities=payload.cities,
            lanes=payload.lanes or None,
            max_queries=payload.max_queries,
            per_query_limit=payload.per_query_limit,
            broad_web=payload.broad_web,
            include_conditional=payload.include_conditional,
            include_investment=payload.include_investment,
            include_subscription=payload.include_subscription,
            actor=principal.actor,
        ).to_dict()
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/health")
def health(
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return discovery_health()
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/campaigns")
def campaigns(
    limit: int = 20,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    try:
        return recent_campaigns(limit=limit)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/campaigns/{campaign_id}")
def campaign(
    campaign_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return get_campaign(campaign_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/sources/{source_key}/reset")
def reset_discovery_source(
    source_key: str,
    principal: Principal = Depends(require_roles(ADMIN)),
) -> dict[str, Any]:
    del principal
    try:
        return reset_source(source_key)
    except Exception as exc:
        raise _translate(exc) from exc
