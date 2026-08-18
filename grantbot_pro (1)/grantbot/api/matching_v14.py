from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.matching.competitive_v14 import (
    analyze_competitiveness,
)


router = APIRouter(
    prefix="/v14/matching",
    tags=["GrantBot Competitive Matching v14"],
)


class MatchRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=80)
    acquire_if_missing: bool = True


@router.post("/analyze")
def analyze(payload: MatchRequest) -> dict[str, Any]:
    try:
        return analyze_competitiveness(
            payload.opportunity_id,
            acquire_if_missing=payload.acquire_if_missing,
        ).to_dict()

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
