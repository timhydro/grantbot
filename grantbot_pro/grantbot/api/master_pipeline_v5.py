from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.automation.opportunity_pipeline import Opportunity, rank_opportunities
from grantbot.automation.review_router import create_review_folder_from_analysis
from grantbot.eligibility.tax_status import TaxStatus
from grantbot.writing.ollama_provider import OllamaProvider


router = APIRouter(
    prefix="/v5/opportunities",
    tags=["GrantBot Full Opportunity Automation v5"],
)


class OpportunityPayload(BaseModel):
    id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=2, max_length=2000)
    funder: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=100000)
    eligibility: str = Field(default="", max_length=50000)
    deadline: str | None = Field(default=None, max_length=100)
    amount: float | None = Field(default=None, ge=0)
    source_url: str = Field(default="", max_length=5000)
    nofo_text: str = Field(default="", max_length=2_000_000)


class BatchRequest(BaseModel):
    opportunities: list[OpportunityPayload] = Field(min_length=1, max_length=500)
    generate_drafts: bool = False
    create_review_folders: bool = True
    minimum_review_score: int = Field(default=60, ge=0, le=100)
    applicant_tax_status: TaxStatus = TaxStatus.PENDING_501C3
    has_fiscal_sponsor: bool = False


@router.get("/health")
def health() -> dict[str, Any]:
    return OllamaProvider().health()


@router.post("/analyze")
def analyze(payload: BatchRequest) -> dict[str, Any]:
    try:
        results = rank_opportunities(
            [
                Opportunity(**item.model_dump())
                for item in payload.opportunities
            ],
            generate_drafts=payload.generate_drafts,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    review_folders: list[dict[str, str]] = []

    if payload.create_review_folders:
        for result in results:
            folder = create_review_folder_from_analysis(
                result,
                applicant_status=payload.applicant_tax_status,
                has_fiscal_sponsor=payload.has_fiscal_sponsor,
                minimum_score=payload.minimum_review_score,
            )
            if folder:
                review_folders.append(
                    {
                        "opportunity_id": str(result.get("id") or ""),
                        "title": str(result.get("title") or ""),
                        "path": folder,
                    }
                )

    return {
        "count": len(results),
        "high_priority": sum(1 for x in results if x["priority"] == "HIGH"),
        "rejected": sum(1 for x in results if x["hard_reject"]),
        "review_folders_created": len(review_folders),
        "review_folders": review_folders,
        "results": results,
    }
