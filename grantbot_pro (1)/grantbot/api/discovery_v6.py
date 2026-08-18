from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.discovery.grants_gov import (
    DEFAULT_KEYWORDS,
    discover,
)


router = APIRouter(
    prefix="/v6/discovery",
    tags=["GrantBot Live Funding Discovery v6"],
)


class DiscoveryRequest(BaseModel):
    keywords: list[str] = Field(
        default_factory=lambda: list(DEFAULT_KEYWORDS),
        min_length=1,
        max_length=25,
    )
    rows_per_keyword: int = Field(
        default=20,
        ge=1,
        le=100,
    )
    fetch_details: bool = True
    generate_drafts: bool = False


@router.get("/defaults")
def defaults() -> dict[str, Any]:
    return {
        "keywords": list(DEFAULT_KEYWORDS),
        "source": "Grants.gov",
        "statuses": [
            "posted",
            "forecasted",
        ],
    }


@router.post("/search")
def search(
    payload: DiscoveryRequest,
) -> dict[str, Any]:
    try:
        return discover(
            keywords=payload.keywords,
            rows_per_keyword=payload.rows_per_keyword,
            fetch_details=payload.fetch_details,
            generate_drafts=payload.generate_drafts,
        ).to_dict()

    except (
        RuntimeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc
