from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from grantbot.knowledge.integrity_v23 import knowledge_status, prepare_canonical_knowledge
from grantbot.knowledge.profile_v23 import grant_safe_profile, next_questions
from grantbot.security.auth import ADMIN, GRANT_WRITER, REVIEWER, Principal, require_roles


router = APIRouter(prefix="/v23/knowledge", tags=["GrantBot Canonical Knowledge v23"])


@router.get("/status")
def status(
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    return knowledge_status()


@router.get("/questions")
def questions(
    limit: int = Query(default=20, ge=1, le=200),
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        rows = next_questions(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"count": len(rows), "questions": rows}


@router.get("/profile")
def profile(
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    facts = grant_safe_profile()
    return {"count": len(facts), "facts": facts}


@router.post("/seed")
def seed(
    principal: Principal = Depends(require_roles(ADMIN)),
) -> dict[str, Any]:
    return prepare_canonical_knowledge(actor=principal.actor)
