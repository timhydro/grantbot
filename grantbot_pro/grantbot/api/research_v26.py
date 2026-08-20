from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from grantbot.crew_ai.research_service import run_research_suite
from grantbot.crew_ai.research_tools import PROVENANCE_PATH, tools_for_research_agent
from grantbot.security.auth import ADMIN, GRANT_WRITER, REVIEWER, Principal, require_roles
from grantbot.writing.ollama_provider import OllamaProvider


router = APIRouter(prefix="/v26/research", tags=["GrantBot CrewAI Research v26"])


class ResearchRequest(BaseModel):
    research_query: str = Field(default="", max_length=1000)
    opportunity_id: str = Field(default="", max_length=100)


@router.get("/health")
def health(
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    agent_names = [
        "funding_scout",
        "funder_intelligence_analyst",
        "evidence_researcher",
        "knowledge_archivist",
    ]
    return {
        "available": True,
        "paid_api_required": False,
        "default_search_provider": "brave_if_configured_else_ddgs",
        "local_ai": OllamaProvider().health(),
        "agents": {
            name: [tool.name for tool in tools_for_research_agent(name)]
            for name in agent_names
        },
        "provenance_path": str(PROVENANCE_PATH),
    }


@router.post("/run")
def run(
    payload: ResearchRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER, REVIEWER)),
) -> dict[str, Any]:
    del principal
    try:
        result = run_research_suite(
            research_query=payload.research_query,
            opportunity_id=payload.opportunity_id,
        )
        return result.model_dump(mode="json")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
