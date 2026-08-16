from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.compliance.readiness_v15 import (
    evaluate_readiness,
)


router = APIRouter(
    prefix="/v15/readiness",
    tags=["GrantBot Budget Outcomes Compliance v15"],
)


class ReadinessRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=80)


@router.post("/evaluate")
def evaluate(payload: ReadinessRequest) -> dict[str, Any]:
    try:
        return evaluate_readiness(
            payload.opportunity_id
        ).to_dict()

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
