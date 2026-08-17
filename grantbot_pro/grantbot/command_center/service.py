from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Callable

from grantbot.budget.workspace import budget_consistency
from grantbot.compliance.requirements import requirement_summary
from grantbot.discovery.orchestrator import discovery_health
from grantbot.learning.review_learning import learning_profile
from grantbot.postaward.service import award_dashboard, list_awards
from grantbot.review.staging_v17 import list_workspaces
from grantbot.risk.engine import latest_risk


TERMINAL_APPLICATION_STAGES = {"SUBMITTED"}
FINAL_REPORT_STATUSES = {"SUBMITTED", "ACCEPTED", "WAIVED"}
FINAL_TASK_STATUSES = {"DONE", "NOT_APPLICABLE"}


def _as_of(value: str | None) -> date:
    if value is None or not str(value).strip():
        return datetime.now(timezone.utc).date()
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("as_of must be YYYY-MM-DD") from exc


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _date_candidate(value: Any) -> tuple[str, date | None]:
    text = _clean(value)
    if not text:
        return "", None
    candidates = [text]
    if "T" in text:
        candidates.append(text.split("T", 1)[0])
    for candidate in candidates:
        try:
            parsed = date.fromisoformat(candidate[:10])
        except ValueError:
            continue
        return text, parsed
    for pattern in ("%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(text, pattern).date()
        except ValueError:
            continue
        return text, parsed
    return text, None


def _application_deadline(workspace: dict[str, Any]) -> dict[str, Any] | None:
    analysis = workspace.get("analysis") or {}
    blueprint = analysis.get("blueprint") or {}
    sources = [blueprint, analysis]
    keys = (
        "deadline",
        "close_date",
        "closing_date",
        "due_date",
        "submission_deadline",
        "application_deadline",
    )
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            raw, parsed = _date_candidate(source.get(key))
            if raw:
                return {
                    "raw": raw,
                    "date": parsed.isoformat() if parsed else None,
                    "field": key,
                    "parseable": parsed is not None,
                }
    return None


def _safe_call(
    function: Callable[..., Any],
    *args: Any,
    default: Any,
    errors: list[str],
    label: str,
    **kwargs: Any,
) -> Any:
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        errors.append(f"{label}: {type(exc).__name__}: {exc}")
        return default


def _application_row(
    workspace: dict[str, Any],
    *,
    today: date,
) -> dict[str, Any]:
    workspace_id = _clean(workspace.get("workspace_id"))
    errors: list[str] = []
    requirement_gate = _safe_call(
        requirement_summary,
        workspace_id,
        sync=False,
        default={
            "requirement_count": 0,
            "blocking_count": 0,
            "blockers": [],
            "ready": False,
        },
        errors=errors,
        label="requirement_summary",
    )
    budget_gate = _safe_call(
        budget_consistency,
        workspace_id,
        default={
            "budget_required": False,
            "match_required": False,
            "latest_budget": None,
            "approved": False,
            "blockers": [],
            "warnings": [],
        },
        errors=errors,
        label="budget_consistency",
    )
    risk = _safe_call(
        latest_risk,
        workspace_id,
        default=None,
        errors=errors,
        label="latest_risk",
    )

    open_risks = [
        item
        for item in workspace.get("risks", [])
        if _clean(item.get("status")).upper() == "OPEN"
    ]
    pending_checklist = [
        item
        for item in workspace.get("checklist", [])
        if _clean(item.get("status")).upper() == "PENDING"
    ]
    drafts = list(workspace.get("writer_tasks", []))
    incomplete_drafts = [
        item
        for item in drafts
        if _clean(item.get("status")).upper()
        not in {"READY_FOR_REVIEW", "APPROVED"}
        or not _clean(item.get("response"))
    ]

    budget_blockers = [
        _clean(item) for item in budget_gate.get("blockers", []) if _clean(item)
    ]
    requirement_blocking = int(requirement_gate.get("blocking_count", 0) or 0)
    material_blocker_count = (
        len(open_risks)
        + len(pending_checklist)
        + requirement_blocking
        + len(budget_blockers)
        + len(incomplete_drafts)
    )

    latest_budget = budget_gate.get("latest_budget")
    calculation: dict[str, Any] = {}
    if isinstance(latest_budget, dict):
        candidate = latest_budget.get("calculation")
        if isinstance(candidate, dict):
            calculation = candidate
    grant_request = calculation.get("grant_request")
    requested_amount = (
        float(grant_request)
        if isinstance(grant_request, (int, float))
        else None
    )

    deadline = _application_deadline(workspace)
    days_remaining: int | None = None
    deadline_state = "UNKNOWN"
    if deadline is not None and deadline.get("date"):
        parsed = date.fromisoformat(str(deadline["date"]))
        days_remaining = (parsed - today).days
        if days_remaining < 0:
            deadline_state = "PAST_DUE"
        elif days_remaining <= 7:
            deadline_state = "CRITICAL"
        elif days_remaining <= 30:
            deadline_state = "UPCOMING"
        else:
            deadline_state = "OPEN"
    elif deadline is not None:
        deadline_state = "UNPARSEABLE"

    risk_payload = risk if isinstance(risk, dict) else None
    stage = _clean(workspace.get("stage")).upper()
    return {
        "workspace_id": workspace_id,
        "opportunity_id": _clean(workspace.get("opportunity_id")),
        "title": _clean(workspace.get("title")),
        "funder": _clean(workspace.get("funder")),
        "stage": stage,
        "readiness_score": int(workspace.get("readiness_score", 0) or 0),
        "competitive_score": int(workspace.get("competitive_score", 0) or 0),
        "human_approved": bool(workspace.get("human_approved")),
        "writer_task_count": len(drafts),
        "incomplete_draft_count": len(incomplete_drafts),
        "open_risk_count": len(open_risks),
        "pending_checklist_count": len(pending_checklist),
        "authoritative_requirement_count": int(
            requirement_gate.get("requirement_count", 0) or 0
        ),
        "blocking_requirement_count": requirement_blocking,
        "budget_required": bool(budget_gate.get("budget_required")),
        "match_required": bool(budget_gate.get("match_required")),
        "budget_approved": bool(budget_gate.get("approved")),
        "budget_blocker_count": len(budget_blockers),
        "budget_warning_count": len(budget_gate.get("warnings", []) or []),
        "latest_requested_amount": requested_amount,
        "requested_amount_financially_approved": (
            requested_amount if bool(budget_gate.get("approved")) else None
        ),
        "material_blocker_count": material_blocker_count,
        "deadline": deadline,
        "days_to_deadline": days_remaining,
        "deadline_state": deadline_state,
        "risk": (
            {
                "assessment_id": risk_payload.get("assessment_id"),
                "version": risk_payload.get("version"),
                "risk_index": risk_payload.get("risk_index"),
                "risk_band": risk_payload.get("risk_band"),
                "decision": risk_payload.get("decision"),
                "confidence_score": risk_payload.get("confidence_score"),
                "hard_blocker_count": len(
                    risk_payload.get("hard_blockers", []) or []
                ),
                "created_at": risk_payload.get("created_at"),
            }
            if risk_payload
            else None
        ),
        "risk_assessment_state": "ASSESSED" if risk_payload else "NOT_ASSESSED",
        "terminal_stage": stage in TERMINAL_APPLICATION_STAGES,
        "updated_at": _clean(workspace.get("updated_at")),
        "diagnostics": errors,
    }


def application_portfolio(
    *,
    as_of: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    today = _as_of(as_of)
    safe_limit = min(max(int(limit), 1), 1000)
    workspaces = list_workspaces()
    rows = [
        _application_row(workspace, today=today)
        for workspace in workspaces[:safe_limit]
    ]
    stage_counts = Counter(row["stage"] or "UNKNOWN" for row in rows)
    risk_counts = Counter(
        str((row.get("risk") or {}).get("risk_band") or "NOT_ASSESSED")
        for row in rows
    )
    decision_counts = Counter(
        str((row.get("risk") or {}).get("decision") or "NOT_ASSESSED")
        for row in rows
    )
    approved_request_total = round(
        sum(
            float(row["requested_amount_financially_approved"])
            for row in rows
            if row["requested_amount_financially_approved"] is not None
        ),
        2,
    )
    latest_request_total = round(
        sum(
            float(row["latest_requested_amount"])
            for row in rows
            if row["latest_requested_amount"] is not None
        ),
        2,
    )
    return {
        "as_of": today.isoformat(),
        "application_count": len(rows),
        "stage_counts": dict(stage_counts),
        "risk_band_counts": dict(risk_counts),
        "risk_decision_counts": dict(decision_counts),
        "human_approved_count": sum(1 for row in rows if row["human_approved"]),
        "blocked_application_count": sum(
            1 for row in rows if row["material_blocker_count"] > 0
        ),
        "unassessed_risk_count": sum(
            1 for row in rows if row["risk_assessment_state"] == "NOT_ASSESSED"
        ),
        "applications_with_known_deadlines": sum(
            1 for row in rows if (row.get("deadline") or {}).get("date")
        ),
        "past_due_application_count": sum(
            1 for row in rows if row["deadline_state"] == "PAST_DUE"
        ),
        "latest_requested_amount_total": latest_request_total,
        "financially_approved_requested_amount_total": approved_request_total,
        "applications": rows,
        "financial_semantics": (
            "Application requested amounts are proposal/budget values and are not "
            "awards, revenue, cash, or commitments."
        ),
    }


def _award_row(award: dict[str, Any], *, today: date) -> dict[str, Any]:
    award_id = _clean(award.get("award_id"))
    errors: list[str] = []
    dashboard = _safe_call(
        award_dashboard,
        award_id,
        as_of=today.isoformat(),
        default={
            "financial_exposure": {},
            "metrics": [],
            "reports": [],
            "compliance_tasks": [],
            "overdue_report_count": 0,
            "overdue_task_count": 0,
            "next_deadline": None,
            "closeout": {"ready_to_close": False, "blockers": []},
        },
        errors=errors,
        label="award_dashboard",
    )
    exposure = dashboard.get("financial_exposure") or {}
    metrics = dashboard.get("metrics") or []
    measured_metrics = [item for item in metrics if item.get("latest_measurement")]
    target_met = [item for item in measured_metrics if item.get("target_met")]
    return {
        "award_id": award_id,
        "award_number": _clean(award.get("award_number")),
        "workspace_id": _clean(award.get("workspace_id")),
        "opportunity_id": _clean(award.get("opportunity_id")),
        "title": _clean(award.get("title")),
        "funder": _clean(award.get("funder")),
        "status": _clean(award.get("status")).upper(),
        "award_amount": float(award.get("award_amount", 0) or 0),
        "start_date": _clean(award.get("start_date")),
        "end_date": _clean(award.get("end_date")),
        "terms_source": _clean(award.get("terms_source")),
        "spent": float(exposure.get("spent", 0) or 0),
        "remaining": float(exposure.get("remaining", 0) or 0),
        "utilization_pct": float(exposure.get("utilization_pct", 0) or 0),
        "financial_risk_score": float(exposure.get("risk_score", 0) or 0),
        "financial_risk_band": _clean(exposure.get("risk_band")) or "UNKNOWN",
        "financial_signals": list(exposure.get("signals", []) or []),
        "overdue_report_count": int(dashboard.get("overdue_report_count", 0) or 0),
        "overdue_task_count": int(dashboard.get("overdue_task_count", 0) or 0),
        "metric_count": len(metrics),
        "measured_metric_count": len(measured_metrics),
        "target_met_count": len(target_met),
        "next_deadline": dashboard.get("next_deadline"),
        "closeout_ready": bool(
            (dashboard.get("closeout") or {}).get("ready_to_close")
        ),
        "closeout_blocker_count": len(
            (dashboard.get("closeout") or {}).get("blockers", []) or []
        ),
        "diagnostics": errors,
    }


def award_portfolio(
    *,
    as_of: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    today = _as_of(as_of)
    safe_limit = min(max(int(limit), 1), 1000)
    awards = list_awards()
    rows = [
        _award_row(award, today=today)
        for award in awards[:safe_limit]
    ]
    status_counts = Counter(row["status"] or "UNKNOWN" for row in rows)
    financial_band_counts = Counter(row["financial_risk_band"] for row in rows)
    active = [row for row in rows if row["status"] == "ACTIVE"]
    return {
        "as_of": today.isoformat(),
        "award_count": len(rows),
        "active_award_count": len(active),
        "status_counts": dict(status_counts),
        "financial_risk_band_counts": dict(financial_band_counts),
        "total_awarded_amount": round(
            sum(float(row["award_amount"]) for row in rows), 2
        ),
        "active_awarded_amount": round(
            sum(float(row["award_amount"]) for row in active), 2
        ),
        "active_spent": round(sum(float(row["spent"]) for row in active), 2),
        "active_remaining": round(
            sum(float(row["remaining"]) for row in active), 2
        ),
        "overdue_report_count": sum(row["overdue_report_count"] for row in rows),
        "overdue_compliance_task_count": sum(
            row["overdue_task_count"] for row in rows
        ),
        "financial_watch_count": sum(
            1
            for row in rows
            if row["financial_risk_band"] in {"WATCH", "ELEVATED", "HIGH"}
        ),
        "awards": rows,
        "financial_semantics": (
            "Award amounts are recorded post-award terms. Expenditure exposure is "
            "deterministic monitoring, not an audit opinion or probability of funder action."
        ),
    }


def deadline_portfolio(
    *,
    as_of: str | None = None,
    days: int = 90,
    include_past_due: bool = True,
) -> dict[str, Any]:
    today = _as_of(as_of)
    horizon = min(max(int(days), 0), 3650)
    items: list[dict[str, Any]] = []

    applications = application_portfolio(as_of=today.isoformat(), limit=1000)
    for row in applications["applications"]:
        deadline = row.get("deadline") or {}
        deadline_date = deadline.get("date")
        if not deadline_date:
            continue
        due = date.fromisoformat(str(deadline_date))
        remaining = (due - today).days
        if remaining < 0 and not include_past_due:
            continue
        if remaining > horizon:
            continue
        items.append(
            {
                "item_type": "APPLICATION_DEADLINE",
                "id": row["workspace_id"],
                "parent_id": row["workspace_id"],
                "title": row["title"],
                "funder": row["funder"],
                "due_date": due.isoformat(),
                "days_remaining": remaining,
                "status": row["stage"],
                "blocking": remaining < 0 and not row["terminal_stage"],
            }
        )

    awards = list_awards()
    for award in awards:
        dashboard = award_dashboard(
            str(award["award_id"]),
            as_of=today.isoformat(),
        )
        for report in dashboard.get("reports", []):
            if report.get("status") in FINAL_REPORT_STATUSES:
                continue
            due_text = _clean(report.get("due_date"))
            if not due_text:
                continue
            due = date.fromisoformat(due_text)
            remaining = (due - today).days
            if remaining < 0 and not include_past_due:
                continue
            if remaining > horizon:
                continue
            items.append(
                {
                    "item_type": "AWARD_REPORT",
                    "id": report.get("report_id"),
                    "parent_id": award["award_id"],
                    "title": f"{report.get('report_type', 'REPORT')} report",
                    "funder": award.get("funder", ""),
                    "due_date": due.isoformat(),
                    "days_remaining": remaining,
                    "status": report.get("status"),
                    "blocking": bool(report.get("required")) and remaining < 0,
                }
            )
        for task in dashboard.get("compliance_tasks", []):
            if task.get("status") in FINAL_TASK_STATUSES:
                continue
            due_text = _clean(task.get("due_date"))
            if not due_text:
                continue
            due = date.fromisoformat(due_text)
            remaining = (due - today).days
            if remaining < 0 and not include_past_due:
                continue
            if remaining > horizon:
                continue
            items.append(
                {
                    "item_type": "AWARD_COMPLIANCE_TASK",
                    "id": task.get("task_id"),
                    "parent_id": award["award_id"],
                    "title": _clean(task.get("description")),
                    "funder": award.get("funder", ""),
                    "due_date": due.isoformat(),
                    "days_remaining": remaining,
                    "status": task.get("status"),
                    "blocking": bool(task.get("required")) and remaining < 0,
                }
            )

    items.sort(
        key=lambda item: (
            int(item["days_remaining"]),
            str(item["item_type"]),
            str(item["id"]),
        )
    )
    return {
        "as_of": today.isoformat(),
        "horizon_days": horizon,
        "deadline_count": len(items),
        "past_due_count": sum(1 for item in items if item["days_remaining"] < 0),
        "blocking_past_due_count": sum(
            1
            for item in items
            if item["days_remaining"] < 0 and item["blocking"]
        ),
        "due_within_7_days": sum(
            1 for item in items if 0 <= item["days_remaining"] <= 7
        ),
        "due_within_30_days": sum(
            1 for item in items if 0 <= item["days_remaining"] <= 30
        ),
        "deadlines": items,
    }


def portfolio_risks(*, as_of: str | None = None) -> dict[str, Any]:
    today = _as_of(as_of)
    applications = application_portfolio(as_of=today.isoformat(), limit=1000)
    awards = award_portfolio(as_of=today.isoformat(), limit=1000)
    risk_items: list[dict[str, Any]] = []
    for row in applications["applications"]:
        risk = row.get("risk") or {}
        risk_band = str(risk.get("risk_band") or "NOT_ASSESSED")
        if (
            risk_band in {"ELEVATED", "HIGH", "CRITICAL"}
            or row["material_blocker_count"] > 0
            or row["deadline_state"] in {"PAST_DUE", "CRITICAL"}
            or row["risk_assessment_state"] == "NOT_ASSESSED"
        ):
            risk_items.append(
                {
                    "risk_type": "APPLICATION",
                    "id": row["workspace_id"],
                    "title": row["title"],
                    "band": risk_band,
                    "score": risk.get("risk_index"),
                    "decision": risk.get("decision") or "NOT_ASSESSED",
                    "material_blocker_count": row["material_blocker_count"],
                    "deadline_state": row["deadline_state"],
                }
            )
    for row in awards["awards"]:
        if (
            row["financial_risk_band"] in {"WATCH", "ELEVATED", "HIGH"}
            or row["overdue_report_count"] > 0
            or row["overdue_task_count"] > 0
        ):
            risk_items.append(
                {
                    "risk_type": "AWARD",
                    "id": row["award_id"],
                    "title": row["title"],
                    "band": row["financial_risk_band"],
                    "score": row["financial_risk_score"],
                    "decision": "MANAGE",
                    "material_blocker_count": (
                        row["overdue_report_count"] + row["overdue_task_count"]
                    ),
                    "deadline_state": (
                        "PAST_DUE"
                        if row["overdue_report_count"] + row["overdue_task_count"] > 0
                        else "OPEN"
                    ),
                }
            )
    priority = {"CRITICAL": 5, "HIGH": 4, "ELEVATED": 3, "WATCH": 2, "LOW": 1}
    risk_items.sort(
        key=lambda item: (
            priority.get(str(item["band"]), 3),
            int(item.get("material_blocker_count", 0)),
            float(item.get("score") or 0),
        ),
        reverse=True,
    )
    return {
        "as_of": today.isoformat(),
        "risk_item_count": len(risk_items),
        "risks": risk_items,
        "methodology_note": (
            "This list combines deterministic application controls and recorded "
            "post-award financial/compliance signals. It is not an award-probability model."
        ),
    }


def portfolio_summary(*, as_of: str | None = None) -> dict[str, Any]:
    today = _as_of(as_of)
    applications = application_portfolio(as_of=today.isoformat(), limit=1000)
    awards = award_portfolio(as_of=today.isoformat(), limit=1000)
    deadlines = deadline_portfolio(
        as_of=today.isoformat(),
        days=90,
        include_past_due=True,
    )
    discovery_errors: list[str] = []
    discovery = _safe_call(
        discovery_health,
        default={
            "source_count": 0,
            "circuit_open_count": 0,
            "sources": [],
            "campaigns": [],
        },
        errors=discovery_errors,
        label="discovery_health",
    )
    learning_errors: list[str] = []
    learning = _safe_call(
        learning_profile,
        default={
            "review_count": 0,
            "approved_count": 0,
            "approval_rate": 0.0,
            "average_approved_score": None,
            "common_edit_tags": [],
        },
        errors=learning_errors,
        label="learning_profile",
    )
    campaigns = list(discovery.get("campaigns", []) or [])
    latest_campaign = campaigns[0] if campaigns else None
    return {
        "as_of": today.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "applications": {
            key: applications[key]
            for key in (
                "application_count",
                "stage_counts",
                "human_approved_count",
                "blocked_application_count",
                "unassessed_risk_count",
                "past_due_application_count",
                "latest_requested_amount_total",
                "financially_approved_requested_amount_total",
            )
        },
        "awards": {
            key: awards[key]
            for key in (
                "award_count",
                "active_award_count",
                "total_awarded_amount",
                "active_awarded_amount",
                "active_spent",
                "active_remaining",
                "overdue_report_count",
                "overdue_compliance_task_count",
                "financial_watch_count",
            )
        },
        "deadlines": {
            key: deadlines[key]
            for key in (
                "deadline_count",
                "past_due_count",
                "blocking_past_due_count",
                "due_within_7_days",
                "due_within_30_days",
            )
        },
        "discovery": {
            "source_count": int(discovery.get("source_count", 0) or 0),
            "circuit_open_count": int(
                discovery.get("circuit_open_count", 0) or 0
            ),
            "latest_campaign": latest_campaign,
            "diagnostics": discovery_errors,
        },
        "review_learning": {
            "review_count": int(learning.get("review_count", 0) or 0),
            "approved_count": int(learning.get("approved_count", 0) or 0),
            "approval_rate": float(learning.get("approval_rate", 0) or 0),
            "average_approved_score": learning.get("average_approved_score"),
            "common_edit_tags": learning.get("common_edit_tags", []),
            "diagnostics": learning_errors,
        },
        "financial_semantics": {
            "requested_amounts": (
                "Proposal budget requests; not awards, revenue, cash, or commitments."
            ),
            "awarded_amounts": (
                "Recorded post-award terms supported by a source reference."
            ),
        },
        "human_authorization_required": True,
        "autonomous_submission_enabled": False,
    }
