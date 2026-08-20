from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.workflow.control_plane_v27 import (
    advance_run,
    execution_snapshot,
    get_run,
    health,
    list_runs,
    start_run,
    synchronize_run,
)


router = APIRouter(prefix="/v27/workflow", tags=["GrantBot Workflow Control Plane v27"])


class StartRunRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=100)
    manual_urls: list[str] = Field(default_factory=list, max_length=20)
    refresh_analysis: bool = False
    actor: str = Field(default="system", min_length=1, max_length=100)


class AdvanceRunRequest(BaseModel):
    target_stage: str = Field(min_length=1, max_length=50)
    actor: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=5000)


class SyncRunRequest(BaseModel):
    actor: str = Field(default="system", min_length=1, max_length=100)


@router.get("/health")
def workflow_health() -> dict[str, Any]:
    return health()


@router.get("/runs")
def runs() -> list[dict[str, Any]]:
    return list_runs()


@router.post("/runs")
def start(payload: StartRunRequest) -> dict[str, Any]:
    try:
        return start_run(
            payload.opportunity_id,
            manual_urls=payload.manual_urls,
            refresh_analysis=payload.refresh_analysis,
            actor=payload.actor,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
def inspect(run_id: str) -> dict[str, Any]:
    try:
        return get_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/advance")
def advance(run_id: str, payload: AdvanceRunRequest) -> dict[str, Any]:
    try:
        return advance_run(
            run_id,
            target_stage=payload.target_stage,
            actor=payload.actor,
            note=payload.note,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/runs/{run_id}/sync")
def sync(run_id: str, payload: SyncRunRequest) -> dict[str, Any]:
    try:
        return synchronize_run(run_id, actor=payload.actor)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/execution")
def execution(run_id: str) -> dict[str, Any]:
    try:
        return execution_snapshot(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
