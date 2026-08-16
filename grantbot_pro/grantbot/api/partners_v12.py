from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from grantbot.partners.package_builder import build_partner_package, load_partner_package

router = APIRouter(prefix="/v12/partners", tags=["GrantBot Partner Action Engine v12"])

class BuildRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=50)

@router.post("/build")
def build(payload: BuildRequest) -> dict[str, Any]:
    try:
        return build_partner_package(payload.opportunity_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get("/{opportunity_id}")
def get_package(opportunity_id: str) -> dict[str, Any]:
    try:
        return load_partner_package(opportunity_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
