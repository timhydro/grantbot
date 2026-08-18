from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from grantbot.security.auth import ADMIN, GRANT_WRITER, REVIEWER, Principal, require_roles
from grantbot.writing.ollama_provider import OllamaProvider


router = APIRouter(prefix="/v21/local-ai", tags=["GrantBot Local AI v21"])


@router.get("/health")
def local_ai_health(
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    health = OllamaProvider().health()
    return {
        "provider": "ollama",
        "paid_api_required": False,
        **health,
    }
