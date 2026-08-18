from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from grantbot.nofo.full_detail import get_full_nofo_intelligence

router=APIRouter(prefix="/v9/nofo",tags=["Full NOFO Intelligence v9"])
class FullNofoRequest(BaseModel):
    opportunity_id: str = Field(min_length=1,max_length=50)
@router.post("/inspect")
def inspect(payload: FullNofoRequest) -> dict[str,Any]:
    try:
        return get_full_nofo_intelligence(payload.opportunity_id).to_dict()
    except (RuntimeError,ValueError) as exc:
        raise HTTPException(status_code=502,detail=str(exc)) from exc
