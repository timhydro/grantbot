from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.pipeline.live_queue_v16 import (
    DEFAULT_KEYWORDS,
    discover_ranked_queue,
    health,
    load_latest,
    load_run,
    promote_opportunity,
)


router = APIRouter(
    prefix="/v16/queue",
    tags=["GrantBot Live Ranked Queue v16"],
)

compat_router = APIRouter(
    prefix="/v2/grants",
    tags=["GrantBot Batch Matching Compatibility"],
)


class DiscoveryRequest(BaseModel):
    keywords: list[str] = Field(
        default_factory=lambda: list(DEFAULT_KEYWORDS),
        min_length=1,
        max_length=25,
    )
    rows_per_keyword: int = Field(default=10, ge=1, le=50)
    statuses: str = Field(default="posted|forecasted", min_length=1, max_length=80)
    deep_limit: int = Field(default=0, ge=0, le=25)


class PromotionRequest(BaseModel):
    manual_urls: list[str] = Field(default_factory=list, max_length=10)


@router.get("/health")
def queue_health() -> dict[str, Any]:
    return health()


@router.post("/discover")
def discover(payload: DiscoveryRequest) -> dict[str, Any]:
    try:
        return discover_ranked_queue(
            keywords=payload.keywords,
            rows_per_keyword=payload.rows_per_keyword,
            statuses=payload.statuses,
            deep_limit=payload.deep_limit,
        ).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@compat_router.post("/match-batch")
def match_batch(payload: DiscoveryRequest) -> dict[str, Any]:
    return discover(payload)


@router.get("/latest")
def latest() -> dict[str, Any]:
    try:
        return load_latest()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
def run(run_id: str) -> dict[str, Any]:
    try:
        return load_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/promote/{opportunity_id}")
def promote(
    opportunity_id: str,
    payload: PromotionRequest,
) -> dict[str, Any]:
    try:
        return promote_opportunity(
            opportunity_id,
            manual_urls=payload.manual_urls,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
