from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Iterable

from grantbot.core.database import connection, utc_now


AWARD_STATUSES = {"ACTIVE", "SUSPENDED", "CLOSED"}
REPORT_TYPES = {"PROGRAMMATIC", "FINANCIAL", "PERFORMANCE", "CLOSEOUT", "OTHER"}
REPORT_STATUSES = {"DUE", "DRAFT", "READY", "SUBMITTED", "ACCEPTED", "WAIVED"}
TASK_STATUSES = {"OPEN", "DONE", "NOT_APPLICABLE"}


def initialize_postaward_schema() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS postaward_awards_v21 (
                award_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL DEFAULT '',
                opportunity_id TEXT NOT NULL DEFAULT '',
                award_number TEXT NOT NULL,
                title TEXT NOT NULL,
                funder TEXT NOT NULL,
                award_amount REAL NOT NULL CHECK(award_amount >= 0),
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                terms_source TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_by TEXT NOT NULL DEFAULT '',
                closed_at TEXT NOT NULL DEFAULT '',
                UNIQUE(funder, award_number)
            );

            CREATE INDEX IF NOT EXISTS idx_postaward_awards_v21_status
                ON postaward_awards_v21(status, end_date);

            CREATE TABLE IF NOT EXISTS postaward_reports_v21 (
                report_id TEXT PRIMARY KEY,
                award_id TEXT NOT NULL,
                report_type TEXT NOT NULL,
                period_start TEXT NOT NULL DEFAULT '',
                period_end TEXT NOT NULL DEFAULT '',
                due_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DUE',
                required INTEGER NOT NULL DEFAULT 1,
                description TEXT NOT NULL DEFAULT '',
                source_reference TEXT NOT NULL,
                submitted_reference TEXT NOT NULL DEFAULT '',
                accepted_reference TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(award_id)
                    REFERENCES postaward_awards_v21(award_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_postaward_reports_v21_due
                ON postaward_reports_v21(award_id, due_date, status);

            CREATE TABLE IF NOT EXISTS postaward_metrics_v21 (
                metric_id TEXT PRIMARY KEY,
                award_id TEXT NOT NULL,
                name TEXT NOT NULL,
                unit TEXT NOT NULL,
                direction TEXT NOT NULL DEFAULT 'AT_LEAST',
                baseline REAL,
                target REAL NOT NULL,
                target_date TEXT NOT NULL,
                source_reference TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(award_id, name),
                FOREIGN KEY(award_id)
                    REFERENCES postaward_awards_v21(award_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS postaward_measurements_v21 (
                measurement_id TEXT PRIMARY KEY,
                metric_id TEXT NOT NULL,
                measured_on TEXT NOT NULL,
                value REAL NOT NULL,
                evidence_reference TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                recorded_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(metric_id)
                    REFERENCES postaward_metrics_v21(metric_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_postaward_measurements_v21_metric
                ON postaward_measurements_v21(metric_id, measured_on, created_at);

            CREATE TABLE IF NOT EXISTS postaward_expenditures_v21 (
                expenditure_id TEXT PRIMARY KEY,
                award_id TEXT NOT NULL,
                transaction_date TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                payee TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL,
                source_reference TEXT NOT NULL,
                recorded_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(award_id)
                    REFERENCES postaward_awards_v21(award_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_postaward_expenditures_v21_award
                ON postaward_expenditures_v21(award_id, transaction_date, category);

            CREATE TABLE IF NOT EXISTS postaward_compliance_tasks_v21 (
                task_id TEXT PRIMARY KEY,
                award_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                description TEXT NOT NULL,
                due_date TEXT NOT NULL DEFAULT '',
                required INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'OPEN',
                source_reference TEXT NOT NULL,
                evidence_note TEXT NOT NULL DEFAULT '',
                evidence_reference TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(award_id)
                    REFERENCES postaward_awards_v21(award_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_postaward_tasks_v21_gate
                ON postaward_compliance_tasks_v21(award_id, required, status, due_date);

            CREATE TABLE IF NOT EXISTS postaward_events_v21 (
                event_id TEXT PRIMARY KEY,
                award_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(award_id)
                    REFERENCES postaward_awards_v21(award_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_postaward_events_v21_award
                ON postaward_events_v21(award_id, created_at, event_id);
            """
        )


def _clean(value: Any, *, max_length: int = 10000) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > max_length:
        raise ValueError(f"Text exceeds maximum length of {max_length}")
    return text


def _identifier(value: Any, label: str) -> str:
    text = _clean(value, max_length=120)
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", text) or ".." in text:
        raise ValueError(f"Invalid {label}")
    return text


def _iso_date(value: Any, label: str, *, allow_blank: bool = False) -> str:
    text = _clean(value, max_length=32)
    if allow_blank and not text:
        return ""
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD") from exc
    return parsed.isoformat()


def _date_value(value: str) -> date:
    return date.fromisoformat(value)


def _money(value: Any, label: str, *, allow_zero: bool = True) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    if number < 0 or (not allow_zero and number <= 0):
        comparator = "non-negative" if allow_zero else "greater than zero"
        raise ValueError(f"{label} must be {comparator}")
    return round(number, 2)


def _event(
    conn: Any,
    *,
    award_id: str,
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor: str,
    detail: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO postaward_events_v21(
            event_id, award_id, entity_type, entity_id,
            event_type, actor, detail_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            award_id,
            entity_type,
            entity_id,
            event_type,
            actor,
            json.dumps(detail, ensure_ascii=False, sort_keys=True),
            utc_now(),
        ),
    )


def _ensure_award_mutable(conn: Any, award_id: str) -> Any:
    row = conn.execute(
        "SELECT * FROM postaward_awards_v21 WHERE award_id=?",
        (award_id,),
    ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Award not found: {award_id}")
    if str(row["status"]) == "CLOSED":
        raise ValueError("Closed awards are immutable")
    return row


def create_award(
    *,
    award_number: str,
    title: str,
    funder: str,
    award_amount: float,
    start_date: str,
    end_date: str,
    terms_source: str,
    actor: str,
    workspace_id: str = "",
    opportunity_id: str = "",
) -> dict[str, Any]:
    initialize_postaward_schema()
    award_number = _clean(award_number, max_length=200)
    title = _clean(title, max_length=500)
    funder = _clean(funder, max_length=500)
    terms_source = _clean(terms_source, max_length=2000)
    actor = _clean(actor, max_length=500)
    amount = _money(award_amount, "award_amount")
    start = _iso_date(start_date, "start_date")
    end = _iso_date(end_date, "end_date")
    workspace_id = _clean(workspace_id, max_length=120)
    opportunity_id = _clean(opportunity_id, max_length=120)
    if not award_number or not title or not funder or not terms_source or not actor:
        raise ValueError(
            "award_number, title, funder, terms_source, and actor are required"
        )
    if _date_value(end) < _date_value(start):
        raise ValueError("end_date cannot be before start_date")
    award_id = f"awd_{uuid.uuid4().hex}"
    now = utc_now()
    try:
        with connection() as conn:
            conn.execute(
                """
                INSERT INTO postaward_awards_v21(
                    award_id, workspace_id, opportunity_id, award_number,
                    title, funder, award_amount, start_date, end_date,
                    status, terms_source, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
                """,
                (
                    award_id,
                    workspace_id,
                    opportunity_id,
                    award_number,
                    title,
                    funder,
                    amount,
                    start,
                    end,
                    terms_source,
                    actor,
                    now,
                    now,
                ),
            )
            _event(
                conn,
                award_id=award_id,
                entity_type="AWARD",
                entity_id=award_id,
                event_type="AWARD_CREATED",
                actor=actor,
                detail={
                    "award_number": award_number,
                    "award_amount": amount,
                    "start_date": start,
                    "end_date": end,
                    "terms_source": terms_source,
                },
            )
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise ValueError(
                "An award with this funder and award_number already exists"
            ) from exc
        raise
    return get_award(award_id)


def get_award(award_id: str) -> dict[str, Any]:
    initialize_postaward_schema()
    award_id = _identifier(award_id, "award_id")
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM postaward_awards_v21 WHERE award_id=?",
            (award_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Award not found: {award_id}")
    return dict(row)


def list_awards(*, status: str | None = None) -> list[dict[str, Any]]:
    initialize_postaward_schema()
    params: list[Any] = []
    sql = "SELECT * FROM postaward_awards_v21"
    if status is not None:
        normalized = _clean(status, max_length=30).upper()
        if normalized not in AWARD_STATUSES:
            raise ValueError(f"Invalid award status: {normalized}")
        sql += " WHERE status=?"
        params.append(normalized)
    sql += " ORDER BY end_date, funder, award_number"
    with connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def add_report(
    *,
    award_id: str,
    report_type: str,
    due_date: str,
    source_reference: str,
    actor: str,
    period_start: str = "",
    period_end: str = "",
    description: str = "",
    required: bool = True,
) -> dict[str, Any]:
    initialize_postaward_schema()
    award_id = _identifier(award_id, "award_id")
    report_type = _clean(report_type, max_length=50).upper()
    if report_type not in REPORT_TYPES:
        raise ValueError(f"Invalid report_type: {report_type}")
    due = _iso_date(due_date, "due_date")
    p_start = _iso_date(period_start, "period_start", allow_blank=True)
    p_end = _iso_date(period_end, "period_end", allow_blank=True)
    if p_start and p_end and _date_value(p_end) < _date_value(p_start):
        raise ValueError("period_end cannot be before period_start")
    source_reference = _clean(source_reference, max_length=2000)
    description = _clean(description, max_length=5000)
    actor = _clean(actor, max_length=500)
    if not source_reference or not actor:
        raise ValueError("source_reference and actor are required")
    report_id = f"rpt_{uuid.uuid4().hex}"
    now = utc_now()
    with connection() as conn:
        _ensure_award_mutable(conn, award_id)
        conn.execute(
            """
            INSERT INTO postaward_reports_v21(
                report_id, award_id, report_type, period_start, period_end,
                due_date, status, required, description, source_reference,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'DUE', ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                award_id,
                report_type,
                p_start,
                p_end,
                due,
                1 if required else 0,
                description,
                source_reference,
                now,
                now,
            ),
        )
        _event(
            conn,
            award_id=award_id,
            entity_type="REPORT",
            entity_id=report_id,
            event_type="REPORT_SCHEDULED",
            actor=actor,
            detail={
                "report_type": report_type,
                "due_date": due,
                "required": bool(required),
                "source_reference": source_reference,
            },
        )
    return _get_report(report_id)


def _get_report(report_id: str) -> dict[str, Any]:
    initialize_postaward_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM postaward_reports_v21 WHERE report_id=?",
            (report_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Report not found: {report_id}")
    return dict(row)


def set_report_status(
    *,
    award_id: str,
    report_id: str,
    status: str,
    actor: str,
    evidence_reference: str,
) -> dict[str, Any]:
    initialize_postaward_schema()
    award_id = _identifier(award_id, "award_id")
    report_id = _identifier(report_id, "report_id")
    status = _clean(status, max_length=30).upper()
    actor = _clean(actor, max_length=500)
    evidence_reference = _clean(evidence_reference, max_length=2000)
    if status not in REPORT_STATUSES:
        raise ValueError(f"Invalid report status: {status}")
    if not actor:
        raise ValueError("actor is required")
    if status in {"SUBMITTED", "ACCEPTED", "WAIVED"} and not evidence_reference:
        raise ValueError(
            "evidence_reference is required for SUBMITTED, ACCEPTED, or WAIVED"
        )
    now = utc_now()
    with connection() as conn:
        _ensure_award_mutable(conn, award_id)
        row = conn.execute(
            "SELECT * FROM postaward_reports_v21 WHERE award_id=? AND report_id=?",
            (award_id, report_id),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Report not found: {report_id}")
        previous = str(row["status"])
        if status == "ACCEPTED" and previous not in {"SUBMITTED", "ACCEPTED"}:
            raise ValueError("A report must be SUBMITTED before it can be ACCEPTED")
        submitted_reference = str(row["submitted_reference"])
        accepted_reference = str(row["accepted_reference"])
        if status == "SUBMITTED":
            submitted_reference = evidence_reference
        elif status == "ACCEPTED":
            accepted_reference = evidence_reference
        elif status == "WAIVED":
            accepted_reference = evidence_reference
        conn.execute(
            """
            UPDATE postaward_reports_v21
            SET status=?, submitted_reference=?, accepted_reference=?,
                reviewed_by=?, reviewed_at=?, updated_at=?
            WHERE award_id=? AND report_id=?
            """,
            (
                status,
                submitted_reference,
                accepted_reference,
                actor,
                now,
                now,
                award_id,
                report_id,
            ),
        )
        _event(
            conn,
            award_id=award_id,
            entity_type="REPORT",
            entity_id=report_id,
            event_type="REPORT_STATUS_CHANGED",
            actor=actor,
            detail={
                "from": previous,
                "to": status,
                "evidence_reference": evidence_reference,
            },
        )
    return _get_report(report_id)


def add_metric(
    *,
    award_id: str,
    name: str,
    unit: str,
    target: float,
    target_date: str,
    source_reference: str,
    actor: str,
    baseline: float | None = None,
    direction: str = "AT_LEAST",
) -> dict[str, Any]:
    initialize_postaward_schema()
    award_id = _identifier(award_id, "award_id")
    name = _clean(name, max_length=500)
    unit = _clean(unit, max_length=100)
    source_reference = _clean(source_reference, max_length=2000)
    actor = _clean(actor, max_length=500)
    direction = _clean(direction, max_length=30).upper()
    if direction not in {"AT_LEAST", "AT_MOST", "EXACT"}:
        raise ValueError("direction must be AT_LEAST, AT_MOST, or EXACT")
    if not name or not unit or not source_reference or not actor:
        raise ValueError("name, unit, source_reference, and actor are required")
    target_number = float(target)
    if not math.isfinite(target_number):
        raise ValueError("target must be finite")
    baseline_number: float | None = None
    if baseline is not None:
        baseline_number = float(baseline)
        if not math.isfinite(baseline_number):
            raise ValueError("baseline must be finite")
    target_date_value = _iso_date(target_date, "target_date")
    metric_id = f"met_{uuid.uuid4().hex}"
    now = utc_now()
    try:
        with connection() as conn:
            _ensure_award_mutable(conn, award_id)
            conn.execute(
                """
                INSERT INTO postaward_metrics_v21(
                    metric_id, award_id, name, unit, direction, baseline,
                    target, target_date, source_reference, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metric_id,
                    award_id,
                    name,
                    unit,
                    direction,
                    baseline_number,
                    target_number,
                    target_date_value,
                    source_reference,
                    actor,
                    now,
                ),
            )
            _event(
                conn,
                award_id=award_id,
                entity_type="METRIC",
                entity_id=metric_id,
                event_type="METRIC_DEFINED",
                actor=actor,
                detail={
                    "name": name,
                    "unit": unit,
                    "direction": direction,
                    "baseline": baseline_number,
                    "target": target_number,
                    "target_date": target_date_value,
                    "source_reference": source_reference,
                },
            )
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise ValueError(f"Metric already exists for this award: {name}") from exc
        raise
    return _get_metric(metric_id)


def _get_metric(metric_id: str) -> dict[str, Any]:
    initialize_postaward_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM postaward_metrics_v21 WHERE metric_id=?",
            (metric_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Metric not found: {metric_id}")
    return dict(row)


def add_measurement(
    *,
    award_id: str,
    metric_id: str,
    measured_on: str,
    value: float,
    evidence_reference: str,
    actor: str,
    notes: str = "",
) -> dict[str, Any]:
    initialize_postaward_schema()
    award_id = _identifier(award_id, "award_id")
    metric_id = _identifier(metric_id, "metric_id")
    measured = _iso_date(measured_on, "measured_on")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("value must be finite")
    evidence_reference = _clean(evidence_reference, max_length=2000)
    notes = _clean(notes, max_length=5000)
    actor = _clean(actor, max_length=500)
    if not evidence_reference or not actor:
        raise ValueError("evidence_reference and actor are required")
    measurement_id = f"msr_{uuid.uuid4().hex}"
    now = utc_now()
    with connection() as conn:
        _ensure_award_mutable(conn, award_id)
        metric = conn.execute(
            "SELECT award_id FROM postaward_metrics_v21 WHERE metric_id=?",
            (metric_id,),
        ).fetchone()
        if metric is None or str(metric["award_id"]) != award_id:
            raise FileNotFoundError(f"Metric not found for award: {metric_id}")
        conn.execute(
            """
            INSERT INTO postaward_measurements_v21(
                measurement_id, metric_id, measured_on, value,
                evidence_reference, notes, recorded_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                measurement_id,
                metric_id,
                measured,
                numeric,
                evidence_reference,
                notes,
                actor,
                now,
            ),
        )
        _event(
            conn,
            award_id=award_id,
            entity_type="MEASUREMENT",
            entity_id=measurement_id,
            event_type="METRIC_MEASURED",
            actor=actor,
            detail={
                "metric_id": metric_id,
                "measured_on": measured,
                "value": numeric,
                "evidence_reference": evidence_reference,
            },
        )
    return {
        "measurement_id": measurement_id,
        "metric_id": metric_id,
        "award_id": award_id,
        "measured_on": measured,
        "value": numeric,
        "evidence_reference": evidence_reference,
        "notes": notes,
        "recorded_by": actor,
        "created_at": now,
    }


def add_expenditure(
    *,
    award_id: str,
    transaction_date: str,
    category: str,
    amount: float,
    description: str,
    source_reference: str,
    actor: str,
    payee: str = "",
) -> dict[str, Any]:
    initialize_postaward_schema()
    award_id = _identifier(award_id, "award_id")
    transaction = _iso_date(transaction_date, "transaction_date")
    category = _clean(category, max_length=200)
    amount_value = _money(amount, "amount", allow_zero=False)
    description = _clean(description, max_length=5000)
    source_reference = _clean(source_reference, max_length=2000)
    actor = _clean(actor, max_length=500)
    payee = _clean(payee, max_length=500)
    if not category or not description or not source_reference or not actor:
        raise ValueError(
            "category, description, source_reference, and actor are required"
        )
    expenditure_id = f"exp_{uuid.uuid4().hex}"
    now = utc_now()
    with connection() as conn:
        award = _ensure_award_mutable(conn, award_id)
        start = _date_value(str(award["start_date"]))
        end = _date_value(str(award["end_date"]))
        tx_date = _date_value(transaction)
        if tx_date < start or tx_date > end:
            raise ValueError("transaction_date must fall within the award period")
        conn.execute(
            """
            INSERT INTO postaward_expenditures_v21(
                expenditure_id, award_id, transaction_date, category,
                amount, payee, description, source_reference,
                recorded_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                expenditure_id,
                award_id,
                transaction,
                category,
                amount_value,
                payee,
                description,
                source_reference,
                actor,
                now,
            ),
        )
        _event(
            conn,
            award_id=award_id,
            entity_type="EXPENDITURE",
            entity_id=expenditure_id,
            event_type="EXPENDITURE_RECORDED",
            actor=actor,
            detail={
                "transaction_date": transaction,
                "category": category,
                "amount": amount_value,
                "payee": payee,
                "source_reference": source_reference,
            },
        )
    return {
        "expenditure_id": expenditure_id,
        "award_id": award_id,
        "transaction_date": transaction,
        "category": category,
        "amount": amount_value,
        "payee": payee,
        "description": description,
        "source_reference": source_reference,
        "recorded_by": actor,
        "created_at": now,
    }


def add_compliance_task(
    *,
    award_id: str,
    task_type: str,
    description: str,
    source_reference: str,
    actor: str,
    due_date: str = "",
    required: bool = True,
) -> dict[str, Any]:
    initialize_postaward_schema()
    award_id = _identifier(award_id, "award_id")
    task_type = _clean(task_type, max_length=100).upper()
    description = _clean(description, max_length=5000)
    source_reference = _clean(source_reference, max_length=2000)
    actor = _clean(actor, max_length=500)
    due = _iso_date(due_date, "due_date", allow_blank=True)
    if not task_type or not description or not source_reference or not actor:
        raise ValueError(
            "task_type, description, source_reference, and actor are required"
        )
    task_id = f"pct_{uuid.uuid4().hex}"
    now = utc_now()
    with connection() as conn:
        _ensure_award_mutable(conn, award_id)
        conn.execute(
            """
            INSERT INTO postaward_compliance_tasks_v21(
                task_id, award_id, task_type, description, due_date,
                required, status, source_reference, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
            """,
            (
                task_id,
                award_id,
                task_type,
                description,
                due,
                1 if required else 0,
                source_reference,
                now,
                now,
            ),
        )
        _event(
            conn,
            award_id=award_id,
            entity_type="COMPLIANCE_TASK",
            entity_id=task_id,
            event_type="COMPLIANCE_TASK_CREATED",
            actor=actor,
            detail={
                "task_type": task_type,
                "due_date": due,
                "required": bool(required),
                "source_reference": source_reference,
            },
        )
    return _get_task(task_id)


def _get_task(task_id: str) -> dict[str, Any]:
    initialize_postaward_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM postaward_compliance_tasks_v21 WHERE task_id=?",
            (task_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Compliance task not found: {task_id}")
    return dict(row)


def set_compliance_task_status(
    *,
    award_id: str,
    task_id: str,
    status: str,
    actor: str,
    evidence_note: str,
    evidence_reference: str,
    allow_not_applicable: bool = False,
) -> dict[str, Any]:
    initialize_postaward_schema()
    award_id = _identifier(award_id, "award_id")
    task_id = _identifier(task_id, "task_id")
    status = _clean(status, max_length=30).upper()
    actor = _clean(actor, max_length=500)
    evidence_note = _clean(evidence_note, max_length=5000)
    evidence_reference = _clean(evidence_reference, max_length=2000)
    if status not in TASK_STATUSES - {"OPEN"}:
        raise ValueError("status must be DONE or NOT_APPLICABLE")
    if not actor or not evidence_note or not evidence_reference:
        raise ValueError(
            "actor, evidence_note, and evidence_reference are required"
        )
    now = utc_now()
    with connection() as conn:
        _ensure_award_mutable(conn, award_id)
        row = conn.execute(
            "SELECT * FROM postaward_compliance_tasks_v21 WHERE award_id=? AND task_id=?",
            (award_id, task_id),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Compliance task not found: {task_id}")
        if status == "NOT_APPLICABLE":
            if bool(row["required"]):
                raise ValueError("Required compliance tasks cannot be NOT_APPLICABLE")
            if not allow_not_applicable:
                raise PermissionError(
                    "NOT_APPLICABLE requires an authorized compliance reviewer"
                )
        previous = str(row["status"])
        conn.execute(
            """
            UPDATE postaward_compliance_tasks_v21
            SET status=?, evidence_note=?, evidence_reference=?, reviewed_by=?,
                reviewed_at=?, updated_at=?
            WHERE award_id=? AND task_id=?
            """,
            (
                status,
                evidence_note,
                evidence_reference,
                actor,
                now,
                now,
                award_id,
                task_id,
            ),
        )
        _event(
            conn,
            award_id=award_id,
            entity_type="COMPLIANCE_TASK",
            entity_id=task_id,
            event_type="COMPLIANCE_TASK_STATUS_CHANGED",
            actor=actor,
            detail={
                "from": previous,
                "to": status,
                "evidence_note": evidence_note,
                "evidence_reference": evidence_reference,
            },
        )
    return _get_task(task_id)


def _as_of(value: str | None) -> date:
    if value is None or not str(value).strip():
        return datetime.now(timezone.utc).date()
    return _date_value(_iso_date(value, "as_of"))


def financial_exposure(award_id: str, *, as_of: str | None = None) -> dict[str, Any]:
    initialize_postaward_schema()
    award = get_award(award_id)
    as_of_date = _as_of(as_of)
    start = _date_value(str(award["start_date"]))
    end = _date_value(str(award["end_date"]))
    total_days = max(1, (end - start).days + 1)
    elapsed_days = min(total_days, max(0, (as_of_date - start).days + 1))
    elapsed_fraction = elapsed_days / total_days
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT category, SUM(amount) AS total
            FROM postaward_expenditures_v21
            WHERE award_id=? AND transaction_date<=?
            GROUP BY category
            ORDER BY total DESC, category
            """,
            (award_id, as_of_date.isoformat()),
        ).fetchall()
    category_totals = [
        {"category": str(row["category"]), "amount": round(float(row["total"]), 2)}
        for row in rows
    ]
    spent = round(sum(item["amount"] for item in category_totals), 2)
    award_amount = float(award["award_amount"])
    remaining = round(award_amount - spent, 2)
    utilization = spent / award_amount if award_amount > 0 else (1.0 if spent > 0 else 0.0)
    run_rate_projection = (
        spent / elapsed_fraction
        if elapsed_fraction > 0
        else 0.0
    )
    projected_variance = run_rate_projection - award_amount
    burn_variance = utilization - elapsed_fraction
    shares = [item["amount"] / spent for item in category_totals if spent > 0]
    hhi = sum(share * share for share in shares) if shares else 0.0
    signals: list[str] = []
    if spent > award_amount:
        signals.append("Recorded expenditures exceed the award amount.")
    if elapsed_fraction >= 0.25 and run_rate_projection > award_amount * 1.05:
        signals.append("Current run-rate projects an award-period overrun above 5%.")
    if elapsed_fraction >= 0.75 and utilization < 0.50:
        signals.append("Late-period underspend may create execution or closeout risk.")
    if hhi > 0.65 and len(category_totals) > 1:
        signals.append("Expenditures are highly concentrated in a small number of categories.")
    if as_of_date > end and remaining > 0:
        signals.append("Award period has ended with unspent recorded award balance.")
    risk_score = 0.0
    if spent > award_amount:
        risk_score += 55
    elif projected_variance > award_amount * 0.05 and elapsed_fraction >= 0.25:
        risk_score += min(45, max(10, projected_variance / max(award_amount, 1) * 100))
    if elapsed_fraction >= 0.75 and utilization < 0.50:
        risk_score += 25
    if hhi > 0.65 and len(category_totals) > 1:
        risk_score += 10
    risk_score = round(min(100.0, risk_score), 2)
    if risk_score >= 70:
        risk_band = "HIGH"
    elif risk_score >= 40:
        risk_band = "ELEVATED"
    elif risk_score >= 15:
        risk_band = "WATCH"
    else:
        risk_band = "LOW"
    return {
        "award_id": award_id,
        "as_of": as_of_date.isoformat(),
        "award_amount": round(award_amount, 2),
        "spent": spent,
        "remaining": remaining,
        "utilization_pct": round(utilization * 100, 2),
        "elapsed_pct": round(elapsed_fraction * 100, 2),
        "burn_variance_pct_points": round(burn_variance * 100, 2),
        "run_rate_projected_total_spend": round(run_rate_projection, 2),
        "run_rate_projected_variance": round(projected_variance, 2),
        "category_concentration_hhi": round(hhi, 4),
        "category_totals": category_totals,
        "risk_score": risk_score,
        "risk_band": risk_band,
        "signals": signals,
        "methodology_note": (
            "Deterministic expenditure run-rate and concentration analysis based on "
            "recorded transactions and elapsed award period. It is not a probability, "
            "audit opinion, or prediction of funder action."
        ),
    }


def _metric_rows(award_id: str) -> list[dict[str, Any]]:
    initialize_postaward_schema()
    with connection() as conn:
        metrics = conn.execute(
            "SELECT * FROM postaward_metrics_v21 WHERE award_id=? ORDER BY name",
            (award_id,),
        ).fetchall()
        output: list[dict[str, Any]] = []
        for metric in metrics:
            latest = conn.execute(
                """
                SELECT * FROM postaward_measurements_v21
                WHERE metric_id=?
                ORDER BY measured_on DESC, created_at DESC
                LIMIT 1
                """,
                (str(metric["metric_id"]),),
            ).fetchone()
            item = dict(metric)
            item["latest_measurement"] = dict(latest) if latest is not None else None
            if latest is None:
                item["target_met"] = False
                item["attainment_pct"] = None
            else:
                value = float(latest["value"])
                target = float(metric["target"])
                direction = str(metric["direction"])
                if direction == "AT_LEAST":
                    met = value >= target
                elif direction == "AT_MOST":
                    met = value <= target
                else:
                    met = math.isclose(value, target, rel_tol=1e-9, abs_tol=1e-9)
                item["target_met"] = met
                if target == 0:
                    item["attainment_pct"] = 100.0 if met else None
                elif direction == "AT_MOST":
                    item["attainment_pct"] = round(target / value * 100, 2) if value > 0 else 100.0
                else:
                    item["attainment_pct"] = round(value / target * 100, 2)
            output.append(item)
    return output


def closeout_readiness(award_id: str, *, as_of: str | None = None) -> dict[str, Any]:
    initialize_postaward_schema()
    award = get_award(award_id)
    as_of_date = _as_of(as_of)
    blockers: list[str] = []
    warnings: list[str] = []
    with connection() as conn:
        reports = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM postaward_reports_v21 WHERE award_id=? ORDER BY due_date",
                (award_id,),
            ).fetchall()
        ]
        tasks = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM postaward_compliance_tasks_v21 WHERE award_id=? ORDER BY due_date, task_id",
                (award_id,),
            ).fetchall()
        ]
    for report in reports:
        if bool(report["required"]) and report["status"] not in {"SUBMITTED", "ACCEPTED", "WAIVED"}:
            blockers.append(
                f"Required {report['report_type']} report remains {report['status']} "
                f"(due {report['due_date']})."
            )
        elif report["status"] == "SUBMITTED":
            warnings.append(
                f"Report {report['report_id']} is submitted but not recorded as accepted."
            )
    for task in tasks:
        if bool(task["required"]) and task["status"] != "DONE":
            blockers.append(
                f"Required compliance task remains {task['status']}: {task['description']}"
            )
    exposure = financial_exposure(award_id, as_of=as_of_date.isoformat())
    if exposure["spent"] > exposure["award_amount"]:
        blockers.append("Recorded expenditures exceed the award amount.")
    if as_of_date < _date_value(str(award["end_date"])):
        blockers.append("Award period has not ended.")
    metrics = _metric_rows(award_id)
    missing_measurements = [item for item in metrics if item["latest_measurement"] is None]
    if missing_measurements:
        warnings.append(
            f"{len(missing_measurements)} defined performance metric(s) have no recorded measurement."
        )
    unmet = [item for item in metrics if item["latest_measurement"] is not None and not item["target_met"]]
    if unmet:
        warnings.append(
            f"{len(unmet)} measured performance metric(s) are not at their recorded target."
        )
    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    return {
        "award_id": award_id,
        "as_of": as_of_date.isoformat(),
        "ready_to_close": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "financial_exposure": exposure,
        "reports": reports,
        "compliance_tasks": tasks,
        "metrics": metrics,
        "human_closeout_authorization_required": True,
    }


def close_award(*, award_id: str, actor: str, as_of: str | None = None) -> dict[str, Any]:
    initialize_postaward_schema()
    award_id = _identifier(award_id, "award_id")
    actor = _clean(actor, max_length=500)
    if not actor:
        raise ValueError("actor is required")
    readiness = closeout_readiness(award_id, as_of=as_of)
    if not readiness["ready_to_close"]:
        raise ValueError(
            "Award cannot be closed: " + " | ".join(readiness["blockers"])
        )
    now = utc_now()
    with connection() as conn:
        row = conn.execute(
            "SELECT status FROM postaward_awards_v21 WHERE award_id=?",
            (award_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Award not found: {award_id}")
        if str(row["status"]) == "CLOSED":
            return get_award(award_id)
        conn.execute(
            """
            UPDATE postaward_awards_v21
            SET status='CLOSED', closed_by=?, closed_at=?, updated_at=?
            WHERE award_id=?
            """,
            (actor, now, now, award_id),
        )
        _event(
            conn,
            award_id=award_id,
            entity_type="AWARD",
            entity_id=award_id,
            event_type="AWARD_CLOSED",
            actor=actor,
            detail={"as_of": readiness["as_of"]},
        )
    return get_award(award_id)


def list_events(award_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    initialize_postaward_schema()
    award_id = _identifier(award_id, "award_id")
    limit = max(1, min(int(limit), 1000))
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM postaward_events_v21
            WHERE award_id=?
            ORDER BY created_at DESC, event_id DESC
            LIMIT ?
            """,
            (award_id, limit),
        ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["detail"] = json.loads(str(item.pop("detail_json")))
        except json.JSONDecodeError:
            item["detail"] = {}
        output.append(item)
    return output


def award_dashboard(award_id: str, *, as_of: str | None = None) -> dict[str, Any]:
    initialize_postaward_schema()
    award = get_award(award_id)
    as_of_date = _as_of(as_of)
    with connection() as conn:
        reports = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM postaward_reports_v21 WHERE award_id=? ORDER BY due_date",
                (award_id,),
            ).fetchall()
        ]
        tasks = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM postaward_compliance_tasks_v21 WHERE award_id=? ORDER BY due_date, task_id",
                (award_id,),
            ).fetchall()
        ]
    overdue_reports = [
        item
        for item in reports
        if bool(item["required"])
        and item["status"] not in {"SUBMITTED", "ACCEPTED", "WAIVED"}
        and _date_value(str(item["due_date"])) < as_of_date
    ]
    overdue_tasks = [
        item
        for item in tasks
        if bool(item["required"])
        and item["status"] != "DONE"
        and item["due_date"]
        and _date_value(str(item["due_date"])) < as_of_date
    ]
    next_dates: list[tuple[date, str, str]] = []
    for item in reports:
        if item["status"] not in {"SUBMITTED", "ACCEPTED", "WAIVED"}:
            due = _date_value(str(item["due_date"]))
            if due >= as_of_date:
                next_dates.append((due, "REPORT", str(item["report_id"])))
    for item in tasks:
        if item["status"] == "OPEN" and item["due_date"]:
            due = _date_value(str(item["due_date"]))
            if due >= as_of_date:
                next_dates.append((due, "COMPLIANCE_TASK", str(item["task_id"])))
    next_dates.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
    next_deadline = None
    if next_dates:
        next_deadline = {
            "date": next_dates[0][0].isoformat(),
            "type": next_dates[0][1],
            "id": next_dates[0][2],
        }
    metrics = _metric_rows(award_id)
    exposure = financial_exposure(award_id, as_of=as_of_date.isoformat())
    closeout = closeout_readiness(award_id, as_of=as_of_date.isoformat())
    integrity_payload = {
        "award": award,
        "reports": reports,
        "tasks": tasks,
        "metrics": metrics,
        "financial_exposure": exposure,
    }
    fingerprint = hashlib.sha256(
        json.dumps(integrity_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "award": award,
        "as_of": as_of_date.isoformat(),
        "financial_exposure": exposure,
        "metrics": metrics,
        "reports": reports,
        "compliance_tasks": tasks,
        "overdue_report_count": len(overdue_reports),
        "overdue_task_count": len(overdue_tasks),
        "next_deadline": next_deadline,
        "closeout": closeout,
        "state_fingerprint_sha256": fingerprint,
    }
