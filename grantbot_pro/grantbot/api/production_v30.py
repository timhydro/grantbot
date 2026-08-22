from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from grantbot.applications.production_packet import (
    build_production_application_packet,
    builtin_opportunity_path,
    load_opportunity_file,
)
from grantbot.production.master_tool_v30 import production_status_v30, run_adaptive_application_answer
from grantbot.security.auth import ADMIN, GRANT_WRITER, REVIEWER, Principal, require_roles


router = APIRouter(prefix="/v30/production", tags=["GrantBot Production v30"])


class AdaptiveProductionAnswerRequest(BaseModel):
    dossier: str = Field(min_length=1, max_length=300000)
    question: str = Field(min_length=1, max_length=20000)
    max_words: int | None = Field(default=None, ge=1, le=20000)
    section_type: str = Field(default="general", min_length=1, max_length=100)
    funder_archetype: str = Field(default="general", min_length=1, max_length=100)
    budget: dict[str, float] | None = None
    workplan: dict[str, Any] | None = None
    expected_budget_total: float | None = Field(default=None, ge=0)
    run_adversarial_review: bool = False


class ProductionApplicationPacketRequest(BaseModel):
    builtin_opportunity: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    opportunity: dict[str, Any] | None = None
    draft_mode: str = Field(default="template", pattern=r"^(template|local_ai)$")
    supplied_answers: dict[str, str] | None = None
    include_docx: bool = True
    run_adversarial_review: bool = False

    @model_validator(mode="after")
    def one_opportunity_source(self) -> "ProductionApplicationPacketRequest":
        if (self.builtin_opportunity is None) == (self.opportunity is None):
            raise ValueError("Supply exactly one of builtin_opportunity or opportunity")
        return self


@router.get("/status")
def status(
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        return production_status_v30()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post("/answer")
def answer(
    payload: AdaptiveProductionAnswerRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    del principal
    try:
        return run_adaptive_application_answer(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/application-packet")
def application_packet(
    payload: ProductionApplicationPacketRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    del principal
    try:
        if payload.builtin_opportunity:
            opportunity = load_opportunity_file(
                builtin_opportunity_path(payload.builtin_opportunity)
            )
        else:
            opportunity = dict(payload.opportunity or {})
        return build_production_application_packet(
            opportunity,
            draft_mode=payload.draft_mode,
            supplied_answers=payload.supplied_answers,
            include_docx=payload.include_docx,
            run_adversarial_review=payload.run_adversarial_review,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
