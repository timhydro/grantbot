from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.automation.opportunity_pipeline import Opportunity, rank_opportunities
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

    return {
        "count": len(results),
        "high_priority": sum(1 for x in results if x["priority"] == "HIGH"),
        "rejected": sum(1 for x in results if x["hard_reject"]),
        "results": results,
    }
