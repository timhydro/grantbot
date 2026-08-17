from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from grantbot.postaward.service import (
    add_compliance_task,
    add_expenditure,
    add_measurement,
    add_metric,
    add_report,
    award_dashboard,
    close_award,
    closeout_readiness,
    create_award,
    financial_exposure,
    get_award,
    list_awards,
    list_events,
    set_compliance_task_status,
    set_report_status,
)
from grantbot.security.auth import (
    ADMIN,
    AUTHORIZED_REPRESENTATIVE,
    FINANCIAL_REVIEWER,
    GRANT_WRITER,
    REVIEWER,
    Principal,
    require_roles,
)


router = APIRouter(
    prefix="/master/post-award",
    tags=["GrantBot Post-Award Management"],
)

READ_ROLES = (
    ADMIN,
    AUTHORIZED_REPRESENTATIVE,
    FINANCIAL_REVIEWER,
    GRANT_WRITER,
    REVIEWER,
)


class AwardCreateRequest(BaseModel):
    award_number: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    funder: str = Field(min_length=1, max_length=500)
    award_amount: float = Field(ge=0)
    start_date: str = Field(min_length=10, max_length=10)
    end_date: str = Field(min_length=10, max_length=10)
    terms_source: str = Field(min_length=1, max_length=2000)
    workspace_id: str = Field(default="", max_length=120)
    opportunity_id: str = Field(default="", max_length=120)


class ReportCreateRequest(BaseModel):
    report_type: str = Field(min_length=1, max_length=50)
    due_date: str = Field(min_length=10, max_length=10)
    source_reference: str = Field(min_length=1, max_length=2000)
    period_start: str = Field(default="", max_length=10)
    period_end: str = Field(default="", max_length=10)
    description: str = Field(default="", max_length=5000)
    required: bool = True


class ReportStatusRequest(BaseModel):
    status: str = Field(min_length=3, max_length=30)
    evidence_reference: str = Field(default="", max_length=2000)


class MetricCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    unit: str = Field(min_length=1, max_length=100)
    target: float
    target_date: str = Field(min_length=10, max_length=10)
    source_reference: str = Field(min_length=1, max_length=2000)
    baseline: float | None = None
    direction: str = Field(default="AT_LEAST", max_length=30)


class MeasurementCreateRequest(BaseModel):
    measured_on: str = Field(min_length=10, max_length=10)
    value: float
    evidence_reference: str = Field(min_length=1, max_length=2000)
    notes: str = Field(default="", max_length=5000)


class ExpenditureCreateRequest(BaseModel):
    transaction_date: str = Field(min_length=10, max_length=10)
    category: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0)
    description: str = Field(min_length=1, max_length=5000)
    source_reference: str = Field(min_length=1, max_length=2000)
    payee: str = Field(default="", max_length=500)


class ComplianceTaskCreateRequest(BaseModel):
    task_type: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=5000)
    source_reference: str = Field(min_length=1, max_length=2000)
    due_date: str = Field(default="", max_length=10)
    required: bool = True


class ComplianceTaskStatusRequest(BaseModel):
    status: str = Field(min_length=3, max_length=30)
    evidence_note: str = Field(min_length=1, max_length=5000)
    evidence_reference: str = Field(min_length=1, max_length=2000)


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


@router.post("/awards")
def create_award_route(
    payload: AwardCreateRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, AUTHORIZED_REPRESENTATIVE)
    ),
) -> dict[str, Any]:
    try:
        return create_award(
            award_number=payload.award_number,
            title=payload.title,
            funder=payload.funder,
            award_amount=payload.award_amount,
            start_date=payload.start_date,
            end_date=payload.end_date,
            terms_source=payload.terms_source,
            actor=principal.actor,
            workspace_id=payload.workspace_id,
            opportunity_id=payload.opportunity_id,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/awards")
def list_awards_route(
    status: str | None = Query(default=None, max_length=30),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    try:
        return list_awards(status=status)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/awards/{award_id}")
def get_award_route(
    award_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return get_award(award_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/awards/{award_id}/dashboard")
def dashboard_route(
    award_id: str,
    as_of: str | None = Query(default=None, max_length=10),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return award_dashboard(award_id, as_of=as_of)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/awards/{award_id}/financial-exposure")
def financial_exposure_route(
    award_id: str,
    as_of: str | None = Query(default=None, max_length=10),
    principal: Principal = Depends(
        require_roles(ADMIN, AUTHORIZED_REPRESENTATIVE, FINANCIAL_REVIEWER)
    ),
) -> dict[str, Any]:
    del principal
    try:
        return financial_exposure(award_id, as_of=as_of)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/awards/{award_id}/closeout")
def closeout_route(
    award_id: str,
    as_of: str | None = Query(default=None, max_length=10),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return closeout_readiness(award_id, as_of=as_of)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/awards/{award_id}/close")
def close_award_route(
    award_id: str,
    as_of: str | None = Query(default=None, max_length=10),
    principal: Principal = Depends(
        require_roles(ADMIN, AUTHORIZED_REPRESENTATIVE)
    ),
) -> dict[str, Any]:
    try:
        return close_award(
            award_id=award_id,
            actor=principal.actor,
            as_of=as_of,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/awards/{award_id}/reports")
def add_report_route(
    award_id: str,
    payload: ReportCreateRequest,
    principal: Principal = Depends(
        require_roles(
            ADMIN,
            AUTHORIZED_REPRESENTATIVE,
            FINANCIAL_REVIEWER,
            GRANT_WRITER,
            REVIEWER,
        )
    ),
) -> dict[str, Any]:
    try:
        return add_report(
            award_id=award_id,
            report_type=payload.report_type,
            due_date=payload.due_date,
            source_reference=payload.source_reference,
            actor=principal.actor,
            period_start=payload.period_start,
            period_end=payload.period_end,
            description=payload.description,
            required=payload.required,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.put("/awards/{award_id}/reports/{report_id}")
def set_report_status_route(
    award_id: str,
    report_id: str,
    payload: ReportStatusRequest,
    principal: Principal = Depends(
        require_roles(
            ADMIN,
            AUTHORIZED_REPRESENTATIVE,
            FINANCIAL_REVIEWER,
            REVIEWER,
        )
    ),
) -> dict[str, Any]:
    try:
        return set_report_status(
            award_id=award_id,
            report_id=report_id,
            status=payload.status,
            actor=principal.actor,
            evidence_reference=payload.evidence_reference,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/awards/{award_id}/metrics")
def add_metric_route(
    award_id: str,
    payload: MetricCreateRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, REVIEWER)
    ),
) -> dict[str, Any]:
    try:
        return add_metric(
            award_id=award_id,
            name=payload.name,
            unit=payload.unit,
            target=payload.target,
            target_date=payload.target_date,
            source_reference=payload.source_reference,
            actor=principal.actor,
            baseline=payload.baseline,
            direction=payload.direction,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/awards/{award_id}/metrics/{metric_id}/measurements")
def add_measurement_route(
    award_id: str,
    metric_id: str,
    payload: MeasurementCreateRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, REVIEWER)
    ),
) -> dict[str, Any]:
    try:
        return add_measurement(
            award_id=award_id,
            metric_id=metric_id,
            measured_on=payload.measured_on,
            value=payload.value,
            evidence_reference=payload.evidence_reference,
            actor=principal.actor,
            notes=payload.notes,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/awards/{award_id}/expenditures")
def add_expenditure_route(
    award_id: str,
    payload: ExpenditureCreateRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, FINANCIAL_REVIEWER)
    ),
) -> dict[str, Any]:
    try:
        return add_expenditure(
            award_id=award_id,
            transaction_date=payload.transaction_date,
            category=payload.category,
            amount=payload.amount,
            description=payload.description,
            source_reference=payload.source_reference,
            actor=principal.actor,
            payee=payload.payee,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/awards/{award_id}/compliance-tasks")
def add_compliance_task_route(
    award_id: str,
    payload: ComplianceTaskCreateRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, AUTHORIZED_REPRESENTATIVE, REVIEWER)
    ),
) -> dict[str, Any]:
    try:
        return add_compliance_task(
            award_id=award_id,
            task_type=payload.task_type,
            description=payload.description,
            source_reference=payload.source_reference,
            actor=principal.actor,
            due_date=payload.due_date,
            required=payload.required,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.put("/awards/{award_id}/compliance-tasks/{task_id}")
def set_compliance_task_status_route(
    award_id: str,
    task_id: str,
    payload: ComplianceTaskStatusRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, AUTHORIZED_REPRESENTATIVE, REVIEWER)
    ),
) -> dict[str, Any]:
    try:
        return set_compliance_task_status(
            award_id=award_id,
            task_id=task_id,
            status=payload.status,
            actor=principal.actor,
            evidence_note=payload.evidence_note,
            evidence_reference=payload.evidence_reference,
            allow_not_applicable=principal.role
            in {ADMIN, AUTHORIZED_REPRESENTATIVE},
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/awards/{award_id}/events")
def events_route(
    award_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    try:
        return list_events(award_id, limit=limit)
    except Exception as exc:
        raise _translate(exc) from exc
