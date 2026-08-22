from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from grantbot.applications.irs1023 import (
    CORE_QUESTIONS,
    IRSQuestion,
    answer_question,
    build_irs1023_review_packet,
    irs1023_status,
)
from grantbot.security.auth import ADMIN, GRANT_WRITER, REVIEWER, Principal, require_roles


router = APIRouter(
    prefix="/v28/irs1023",
    tags=["GrantBot IRS Form 1023 v28"],
)


class BuildRequest(BaseModel):
    generate_ai: bool = True
    question_ids: list[str] | None = Field(default=None, max_length=50)


class AnswerRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=100)
    part: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=500)
    prompt: str = Field(min_length=1, max_length=20000)
    section: str = Field(default="general", max_length=100)
    max_words: int | None = Field(default=None, ge=1, le=5000)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.get("/status")
def status(
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    return irs1023_status()


@router.get("/questions")
def questions(
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> list[dict[str, Any]]:
    del principal
    return [question.to_dict() for question in CORE_QUESTIONS]


@router.post("/answer")
def answer(
    payload: AnswerRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    del principal
    try:
        question = IRSQuestion(
            question_id=payload.question_id,
            part=payload.part,
            label=payload.label,
            prompt=payload.prompt,
            section=payload.section,
            max_words=payload.max_words,
        )
        return answer_question(question)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/build")
def build(
    payload: BuildRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    del principal
    try:
        valid_ids = {question.question_id for question in CORE_QUESTIONS}
        if payload.question_ids is not None:
            unknown = sorted(set(payload.question_ids) - valid_ids)
            if unknown:
                raise ValueError(f"Unknown IRS Form 1023 question id(s): {', '.join(unknown)}")
        packet, folder, ai_results = build_irs1023_review_packet(
            generate_ai=payload.generate_ai,
            question_ids=payload.question_ids,
        )
        return {
            "packet": packet.to_dict(),
            "folder": folder,
            "ai_results": ai_results,
            "human_review_required": True,
            "submission_performed": False,
            "safe_to_submit": False,
        }
    except Exception as exc:
        raise _error(exc) from exc
