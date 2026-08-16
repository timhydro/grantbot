from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.discovery.grants_gov import DEFAULT_KEYWORDS
from grantbot.orchestration.orchestrator_v11 import run_v11


router = APIRouter(
    prefix="/v11/orchestrator",
    tags=["GrantBot Role-Aware Orchestrator v11"],
)


class RunRequest(BaseModel):
    keywords: list[str] = Field(
        default_factory=lambda: list(DEFAULT_KEYWORDS),
        min_length=1,
        max_length=25,
    )
    rows_per_keyword: int = Field(default=10, ge=1, le=100)
    minimum_score: int = Field(default=60, ge=0, le=100)
    maximum_direct_packages: int = Field(default=10, ge=1, le=50)
    generate_drafts: bool = False
    fetch_details: bool = True


@router.post("/run")
def run(payload: RunRequest) -> dict[str, Any]:
    try:
        return run_v11(**payload.model_dump())
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
