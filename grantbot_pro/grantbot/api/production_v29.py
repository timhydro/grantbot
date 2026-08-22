from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from grantbot.production.master_tool import (
    build_irs1023_production_packet,
    production_status,
    run_application_answer,
)
from grantbot.security.auth import ADMIN, GRANT_WRITER, REVIEWER, Principal, require_roles


router = APIRouter(
    prefix="/v29/production",
    tags=["GrantBot Production v29"],
)


class ProductionAnswerRequest(BaseModel):
    dossier: str = Field(min_length=1, max_length=300000)
    question: str = Field(min_length=1, max_length=20000)
    max_words: int | None = Field(default=None, ge=1, le=20000)
    section_type: str = Field(default="general", max_length=100)
    funder_archetype: str = Field(default="general", max_length=100)


class IRS1023BuildRequest(BaseModel):
    generate_ai: bool = True
    question_ids: list[str] | None = Field(default=None, max_length=100)


@router.get("/status")
def status(
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        return production_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post("/answer")
def answer(
    payload: ProductionAnswerRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    del principal
    try:
        return run_application_answer(
            dossier=payload.dossier,
            question=payload.question,
            max_words=payload.max_words,
            section_type=payload.section_type,
            funder_archetype=payload.funder_archetype,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/irs1023/build")
def build_irs1023(
    payload: IRS1023BuildRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    del principal
    try:
        return build_irs1023_production_packet(
            generate_ai=payload.generate_ai,
            question_ids=payload.question_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
