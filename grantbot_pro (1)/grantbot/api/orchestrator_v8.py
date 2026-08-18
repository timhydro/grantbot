from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from grantbot.discovery.grants_gov import DEFAULT_KEYWORDS
from grantbot.orchestration.application_orchestrator import run_orchestration, load_latest_queue

router = APIRouter(prefix="/v8/orchestrator", tags=["Application Orchestrator v8"])

class RunRequest(BaseModel):
    keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_KEYWORDS), min_length=1, max_length=25)
    rows_per_keyword: int = Field(default=10, ge=1, le=100)
    minimum_score: int = Field(default=80, ge=0, le=100)
    maximum_packages: int = Field(default=10, ge=1, le=50)
    generate_drafts: bool = True
    fetch_details: bool = True

@router.post("/run")
def run(payload: RunRequest) -> dict[str, Any]:
    try:
        return run_orchestration(**payload.model_dump())
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@router.get("/latest")
def latest() -> dict[str, Any]:
    try:
        return load_latest_queue()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
