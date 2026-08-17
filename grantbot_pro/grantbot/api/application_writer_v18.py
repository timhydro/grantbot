from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from grantbot.security.auth import ADMIN, GRANT_WRITER, REVIEWER, Principal, require_roles
from grantbot.writer.application_writer_v18 import draft_task, submit_feedback


router = APIRouter(prefix="/v18/writer", tags=["GrantBot Application Writer v18"])


class DraftRequest(BaseModel):
    max_words: int | None = Field(default=None, ge=1, le=20000)


class FeedbackRequest(BaseModel):
    revision_id: str | None = Field(default=None, max_length=100)
    before_text: str = Field(default="", max_length=200000)
    after_text: str = Field(default="", max_length=200000)
    accepted: bool = False
    edit_tags: list[str] = Field(default_factory=list, max_length=50)
    reviewer: str = Field(default="", max_length=200)
    reviewer_score: float | None = Field(default=None, ge=0, le=100)
    outcome: str = Field(default="", max_length=200)
    award_amount: float | None = Field(default=None, ge=0)
    section_type: str = Field(default="general", max_length=100)
    funder_archetype: str = Field(default="general", max_length=100)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.post("/{workspace_id}/{task_id}/draft")
def draft(
    workspace_id: str,
    task_id: str,
    payload: DraftRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    del principal
    try:
        return draft_task(workspace_id, task_id, max_words=payload.max_words)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/{workspace_id}/{task_id}/feedback")
def feedback(
    workspace_id: str,
    task_id: str,
    payload: FeedbackRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    try:
        return submit_feedback(
            workspace_id=workspace_id,
            task_id=task_id,
            revision_id=payload.revision_id,
            before_text=payload.before_text,
            after_text=payload.after_text,
            accepted=payload.accepted,
            edit_tags=payload.edit_tags,
            reviewer=principal.actor,
            reviewer_score=payload.reviewer_score,
            outcome=payload.outcome,
            award_amount=payload.award_amount,
            section_type=payload.section_type,
            funder_archetype=payload.funder_archetype,
        )
    except Exception as exc:
        raise _error(exc) from exc
