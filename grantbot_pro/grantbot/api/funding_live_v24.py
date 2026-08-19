from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.eligibility.tax_status import TaxStatus
from grantbot.funding.live_runner import OFFICIAL_SOURCE_PAGES, run_live_discovery
from grantbot.funding.registry import registry_stats, seed_catalog


router = APIRouter(
    prefix="/v24/funding",
    tags=["GrantBot Alternative Capital Discovery v24"],
)


class LiveFundingRequest(BaseModel):
    state: str = Field(default="Florida", min_length=2, max_length=100)
    counties: list[str] = Field(default_factory=lambda: ["Escambia"], max_length=25)
    cities: list[str] = Field(default_factory=lambda: ["Pensacola"], max_length=25)
    lanes: list[str] | None = None
    max_terms_per_lane: int = Field(default=2, ge=1, le=10)
    per_query_limit: int = Field(default=15, ge=1, le=100)
    maximum_queries: int = Field(default=100, ge=1, le=1000)
    minimum_review_score: int = Field(default=60, ge=0, le=100)
    applicant_tax_status: TaxStatus = TaxStatus.PENDING_501C3
    has_fiscal_sponsor: bool = False
    create_review_folders: bool = True


@router.get("/health")
def health() -> dict[str, Any]:
    stats = registry_stats()
    return {
        "status": "ok",
        "version": 24,
        "module": "alternative_capital_discovery",
        "registered_sources": stats.get("active_sources", 0),
        "live_page_adapters": sorted(OFFICIAL_SOURCE_PAGES),
        "default_tax_status": TaxStatus.PENDING_501C3.value,
    }


@router.post("/seed")
def seed() -> dict[str, Any]:
    count = seed_catalog()
    return {"seeded": count, "registry": registry_stats()}


@router.post("/discover")
def discover(payload: LiveFundingRequest) -> dict[str, Any]:
    try:
        result = run_live_discovery(
            state=payload.state,
            counties=payload.counties,
            cities=payload.cities,
            lanes=payload.lanes,
            max_terms_per_lane=payload.max_terms_per_lane,
            per_query_limit=payload.per_query_limit,
            maximum_queries=payload.maximum_queries,
            minimum_review_score=payload.minimum_review_score,
            applicant_tax_status=payload.applicant_tax_status,
            has_fiscal_sponsor=payload.has_fiscal_sponsor,
            create_review_folders=payload.create_review_folders,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result.to_dict()
