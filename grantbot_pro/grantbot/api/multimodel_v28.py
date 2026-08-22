from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from grantbot.agents.crewai_multimodel import (
    extract_final_answer,
    kickoff_multimodel_grant_crew,
    role_plan_status,
)
from grantbot.security.auth import ADMIN, GRANT_WRITER, REVIEWER, Principal, require_roles


router = APIRouter(
    prefix="/v28/multimodel",
    tags=["GrantBot Multi-Model Intelligence v28"],
)


class MultiModelAnswerRequest(BaseModel):
    dossier: str = Field(min_length=1, max_length=250000)
    question: str = Field(min_length=1, max_length=20000)
    max_words: int | None = Field(default=None, ge=1, le=10000)


@router.get("/status")
def status(
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    return role_plan_status()


@router.post("/answer")
def answer(
    payload: MultiModelAnswerRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    del principal
    try:
        result = kickoff_multimodel_grant_crew(
            dossier=payload.dossier,
            question=payload.question,
            max_words=payload.max_words,
        )
        data = result.to_dict()
        data["final_answer"] = extract_final_answer(result.output)
        return data
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
