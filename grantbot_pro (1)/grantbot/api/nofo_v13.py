from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.nofo.acquisition_v13 import (
    acquire_blueprint,
    load_blueprint,
)


router = APIRouter(
    prefix="/v13/nofo",
    tags=["GrantBot NOFO Acquisition v13"],
)


class AcquireRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=80)
    manual_urls: list[str] = Field(default_factory=list, max_length=10)


@router.post("/acquire")
def acquire(payload: AcquireRequest) -> dict[str, Any]:
    try:
        return acquire_blueprint(
            payload.opportunity_id,
            manual_urls=payload.manual_urls,
        ).to_dict()

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{opportunity_id}")
def get_blueprint(opportunity_id: str) -> dict[str, Any]:
    try:
        return load_blueprint(opportunity_id)

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
