from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from grantbot.learning.review_learning import (
    DIMENSION_WEIGHTS,
    approved_examples,
    learning_profile,
    review_history,
    submit_review,
)
from grantbot.security.auth import (
    ADMIN,
    AUTHORIZED_REPRESENTATIVE,
    GRANT_WRITER,
    REVIEWER,
    Principal,
    require_roles,
)


router = APIRouter(
    prefix="/master/review-learning",
    tags=["GrantBot Human Review and Adaptive Learning"],
)


class ReviewRequest(BaseModel):
    decision: str = Field(min_length=3, max_length=20)
    dimensions: dict[str, float]
    rationale: str = Field(min_length=1, max_length=10000)
    edit_tags: list[str] = Field(default_factory=list, max_length=50)
    final_text: str = Field(default="", max_length=200000)
    section_type: str = Field(default="", max_length=100)
    funder_archetype: str = Field(default="", max_length=100)
    outcome: str = Field(default="", max_length=200)
    award_amount: float | None = Field(default=None, ge=0)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(
        status_code=500,
        detail=f"{type(exc).__name__}: {exc}",
    )


@router.get("/rubric")
def rubric(
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, REVIEWER, AUTHORIZED_REPRESENTATIVE)
    ),
) -> dict[str, Any]:
    del principal
    return {
        "dimensions": DIMENSION_WEIGHTS,
        "decisions": ["APPROVE", "REVISE", "REJECT"],
        "approval_threshold": 80,
        "minimum_dimension_for_approval": 65,
        "learning_policy": (
            "Only adjudicated APPROVE reviews enter the reusable example library. "
            "Examples are style/structure references only and never factual evidence."
        ),
    }


@router.post("/{workspace_id}/{task_id}/{revision_id}")
def review_revision(
    workspace_id: str,
    task_id: str,
    revision_id: str,
    payload: ReviewRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    try:
        return submit_review(
            workspace_id=workspace_id,
            task_id=task_id,
            revision_id=revision_id,
            decision=payload.decision,
            dimensions=payload.dimensions,
            rationale=payload.rationale,
            edit_tags=payload.edit_tags,
            reviewer=principal.actor,
            final_text=payload.final_text,
            section_type=payload.section_type,
            funder_archetype=payload.funder_archetype,
            outcome=payload.outcome,
            award_amount=payload.award_amount,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/{workspace_id}/history")
def get_review_history(
    workspace_id: str,
    task_id: str | None = Query(default=None, max_length=100),
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, REVIEWER, AUTHORIZED_REPRESENTATIVE)
    ),
) -> list[dict[str, Any]]:
    del principal
    try:
        return review_history(workspace_id, task_id=task_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/learning/examples")
def get_learning_examples(
    query: str = Query(min_length=1, max_length=5000),
    section_type: str = Query(default="general", max_length=100),
    funder_archetype: str = Query(default="general", max_length=100),
    limit: int = Query(default=3, ge=1, le=10),
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, REVIEWER, AUTHORIZED_REPRESENTATIVE)
    ),
) -> list[dict[str, Any]]:
    del principal
    try:
        return approved_examples(
            query=query,
            section_type=section_type,
            funder_archetype=funder_archetype,
            limit=limit,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/learning/profile")
def get_learning_profile(
    section_type: str | None = Query(default=None, max_length=100),
    funder_archetype: str | None = Query(default=None, max_length=100),
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, REVIEWER, AUTHORIZED_REPRESENTATIVE)
    ),
) -> dict[str, Any]:
    del principal
    try:
        return learning_profile(
            section_type=section_type,
            funder_archetype=funder_archetype,
        )
    except Exception as exc:
        raise _translate(exc) from exc
