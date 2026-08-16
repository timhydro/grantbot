from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.eligibility.applicant_role import classify_applicant_role
from grantbot.nofo.full_detail import get_full_nofo_intelligence

router = APIRouter(
    prefix="/v10/eligibility",
    tags=["GrantBot Applicant Role Classifier v10"],
)

class RoleRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=50)

@router.post("/classify")
def classify(payload: RoleRequest) -> dict[str, Any]:
    try:
        full = get_full_nofo_intelligence(payload.opportunity_id)

        role = classify_applicant_role(
            eligibility=full.eligibility,
            existing_blockers=list(
                full.eligibility_gate.get("blockers", [])
            ),
        )

        return {
            "opportunity_id": full.opportunity_id,
            "title": full.title,
            "eligibility": full.eligibility,
            "cost_sharing": full.cost_sharing,
            "v9_gate": full.eligibility_gate,
            "applicant_role": role.to_dict(),
        }

    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
