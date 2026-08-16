from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.applications.package_builder import (
    build_application_package,
    load_application_package,
)
from grantbot.automation.opportunity_pipeline import Opportunity


router = APIRouter(
    prefix="/v7/applications",
    tags=["GrantBot Application Package Builder v7"],
)


class BuildRequest(BaseModel):
    id: str = Field(
        min_length=1,
        max_length=500,
    )
    title: str = Field(
        min_length=2,
        max_length=2000,
    )
    funder: str = Field(
        default="",
        max_length=2000,
    )
    description: str = Field(
        default="",
        max_length=100000,
    )
    eligibility: str = Field(
        default="",
        max_length=50000,
    )
    deadline: str | None = Field(
        default=None,
        max_length=100,
    )
    amount: float | None = Field(
        default=None,
        ge=0,
    )
    source_url: str = Field(
        default="",
        max_length=5000,
    )
    nofo_text: str = Field(
        default="",
        max_length=2_000_000,
    )
    generate_drafts: bool = True


@router.post("/build")
def build(
    payload: BuildRequest,
) -> dict[str, Any]:
    try:
        opportunity = Opportunity(
            id=payload.id,
            title=payload.title,
            funder=payload.funder,
            description=payload.description,
            eligibility=payload.eligibility,
            deadline=payload.deadline,
            amount=payload.amount,
            source_url=payload.source_url,
            nofo_text=payload.nofo_text,
        )

        return build_application_package(
            opportunity,
            generate_drafts=payload.generate_drafts,
        ).to_dict()

    except (
        RuntimeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.get("/{package_id}")
def get_package(
    package_id: str,
) -> dict[str, Any]:
    try:
        return load_application_package(
            package_id
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
