from __future__ import annotations

import hashlib
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from grantbot.budget.engine import calculate_budget
from grantbot.core.database import connection, utc_now
from grantbot.review.staging_v17 import get_workspace


MONEY_TOKEN = r"\$?\s*\d[\d,]*(?:\.\d+)?(?:\s*(?:million|thousand|m|k))?"
PERCENT_TOKEN = r"\d+(?:\.\d+)?\s*%"
INTEGER_TOKEN = r"\d[\d,]*"

MONEY_PATTERNS = {
    "grant_request": (
        re.compile(
            rf"\b(?:grant|funding|award)\s+(?:request|requested|requesting|sought|seeking|amount)\b"
            rf"[^$\d]{{0,40}}(?P<value>{MONEY_TOKEN})",
            re.I,
        ),
        re.compile(
            rf"\b(?:requesting|seeking|request)\b[^$\d]{{0,35}}(?P<value>{MONEY_TOKEN})"
            rf"[^.\n]{{0,30}}\b(?:grant|funding|award)\b",
            re.I,
        ),
    ),
    "total_project_cost": (
        re.compile(
            rf"\b(?:total\s+project\s+cost|total\s+project\s+budget|project\s+total)\b"
            rf"[^$\d]{{0,40}}(?P<value>{MONEY_TOKEN})",
            re.I,
        ),
    ),
    "cash_match": (
        re.compile(
            rf"\b(?:cash\s+match|cash\s+contribution|cash\s+cost[- ]share)\b"
            rf"[^$\d]{{0,40}}(?P<value>{MONEY_TOKEN})",
            re.I,
        ),
    ),
    "in_kind_match": (
        re.compile(
            rf"\b(?:in[- ]kind\s+match|in[- ]kind\s+contribution|in[- ]kind\s+cost[- ]share)\b"
            rf"[^$\d]{{0,40}}(?P<value>{MONEY_TOKEN})",
            re.I,
        ),
    ),
}

RATE_PATTERNS = (
    re.compile(
        rf"\b(?:indirect|indirect\s+cost|administrative)\s+rate\b"
        rf"[^\d]{{0,30}}(?P<value>{PERCENT_TOKEN})",
        re.I,
    ),
)

COUNT_PATTERNS = {
    "participant_count": (
        re.compile(
            rf"\b(?:serve|serving|serve up to|serve approximately|participant target(?:\s+of)?|target(?:ing)?(?:\s+approximately)?)\b"
            rf"[^\d]{{0,25}}(?P<value>{INTEGER_TOKEN})\s+"
            r"(?:participants?|people|individuals?|residents?|clients?)\b",
            re.I,
        ),
    ),
    "housing_unit_count": (
        re.compile(
            rf"\b(?:develop|build|construct|provide|operate|create|initial(?:ly)?|capacity(?:\s+of)?)\b"
            rf"[^\d]{{0,25}}(?P<value>{INTEGER_TOKEN})\s+"
            r"(?:tiny\s+homes?|housing\s+units?|units?)\b",
            re.I,
        ),
    ),
}

NO_MATCH_RE = re.compile(
    r"\b(?:no|without)\s+(?:non[- ]federal\s+)?(?:match|matching|cost[- ]sharing)\b|"
    r"\b(?:match|matching|cost[- ]sharing)\s+(?:is|are)\s+not\s+required\b",
    re.I,
)



def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def initialize_budget_schema() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS budget_snapshots_v20 (
                budget_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                input_json TEXT NOT NULL,
                calculation_json TEXT NOT NULL,
                calculation_sha256 TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(workspace_id, version)
            );

            CREATE INDEX IF NOT EXISTS idx_budget_snapshots_v20_workspace
                ON budget_snapshots_v20(workspace_id, version DESC);

            CREATE TABLE IF NOT EXISTS budget_approvals_v20 (
                budget_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                approval_note TEXT NOT NULL,
                approved_at TEXT NOT NULL,
                FOREIGN KEY(budget_id) REFERENCES budget_snapshots_v20(budget_id)
                    ON DELETE CASCADE
            );
            """
        )


def _decode_budget(row: Any, approval: Any = None) -> dict[str, Any]:
    item = dict(row)
    item["inputs"] = json.loads(str(item.pop("input_json")))
    item["calculation"] = json.loads(str(item.pop("calculation_json")))
    if approval is None:
        item["approved"] = False
        item["approval"] = None
    else:
        item["approved"] = True
        item["approval"] = dict(approval)
    return item


def save_workspace_budget(
    workspace_id: str,
    *,
    items: list[dict[str, Any]],
    indirect_rate_percent: float = 0.0,
    indirect_base_categories: list[str] | None = None,
    cash_match: float = 0.0,
    in_kind_match: float = 0.0,
    participant_count: int | None = None,
    housing_unit_count: int | None = None,
    actor: str,
) -> dict[str, Any]:
    initialize_budget_schema()
    get_workspace(workspace_id)
    actor = str(actor).strip()
    if not actor:
        raise ValueError("actor is required")
    inputs = {
        "items": items,
        "indirect_rate_percent": indirect_rate_percent,
        "indirect_base_categories": indirect_base_categories,
        "cash_match": cash_match,
        "in_kind_match": in_kind_match,
        "participant_count": participant_count,
        "housing_unit_count": housing_unit_count,
    }
    calculation = calculate_budget(**inputs)
    calculation["participant_count"] = participant_count
    calculation["housing_unit_count"] = housing_unit_count
    budget_id = uuid.uuid4().hex
    now = utc_now()
    with connection() as conn:
        current = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM budget_snapshots_v20 "
            "WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        version = int(current[0]) + 1
        conn.execute(
            """
            INSERT INTO budget_snapshots_v20(
                budget_id, workspace_id, version, input_json,
                calculation_json, calculation_sha256, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                budget_id,
                workspace_id,
                version,
                _canonical(inputs),
                _canonical(calculation),
                _sha(calculation),
                actor,
                now,
            ),
        )
    return get_budget(budget_id)


def get_budget(budget_id: str) -> dict[str, Any]:
    initialize_budget_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM budget_snapshots_v20 WHERE budget_id=?",
            (budget_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Budget not found: {budget_id}")
        approval = conn.execute(
            "SELECT * FROM budget_approvals_v20 WHERE budget_id=?",
            (budget_id,),
        ).fetchone()
    return _decode_budget(row, approval)


def latest_budget(workspace_id: str) -> dict[str, Any] | None:
    initialize_budget_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM budget_snapshots_v20 "
            "WHERE workspace_id=? ORDER BY version DESC LIMIT 1",
            (workspace_id,),
        ).fetchone()
        if row is None:
            return None
        approval = conn.execute(
            "SELECT * FROM budget_approvals_v20 WHERE budget_id=?",
            (str(row["budget_id"]),),
        ).fetchone()
    return _decode_budget(row, approval)


def budget_history(workspace_id: str) -> list[dict[str, Any]]:
    initialize_budget_schema()
    get_workspace(workspace_id)
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM budget_snapshots_v20 "
            "WHERE workspace_id=? ORDER BY version DESC",
            (workspace_id,),
        ).fetchall()
        approvals = {
            str(row["budget_id"]): row
            for row in conn.execute(
                "SELECT * FROM budget_approvals_v20 WHERE workspace_id=?",
                (workspace_id,),
            ).fetchall()
        }
    return [
        _decode_budget(row, approvals.get(str(row["budget_id"])))
        for row in rows
    ]


def approve_budget(
    workspace_id: str,
    budget_id: str,
    *,
    actor: str,
    note: str,
) -> dict[str, Any]:
    initialize_budget_schema()
    actor = str(actor).strip()
    note = str(note).strip()
    if not actor or not note:
        raise ValueError("actor and note are required")
    latest = latest_budget(workspace_id)
    if latest is None:
        raise FileNotFoundError(f"No budget exists for workspace: {workspace_id}")
    if latest["budget_id"] != budget_id:
        raise ValueError("Only the latest budget version can be approved")
    consistency = budget_consistency(workspace_id, require_approval=False)
    if consistency["blockers"]:
        raise ValueError(
            "Budget consistency blockers must be resolved before approval: "
            + "; ".join(consistency["blockers"])
        )
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO budget_approvals_v20(
                budget_id, workspace_id, approved_by, approval_note, approved_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(budget_id) DO UPDATE SET
                approved_by=excluded.approved_by,
                approval_note=excluded.approval_note,
                approved_at=excluded.approved_at
            """,
            (budget_id, workspace_id, actor, note, now),
        )
    return get_budget(budget_id)


def _parse_money(raw: str) -> float:
    text = raw.strip().lower().replace("$", "").replace(",", "")
    multiplier = Decimal("1")
    if text.endswith("million"):
        multiplier = Decimal("1000000")
        text = text[: -len("million")].strip()
    elif text.endswith("thousand"):
        multiplier = Decimal("1000")
        text = text[: -len("thousand")].strip()
    elif text.endswith("m"):
        multiplier = Decimal("1000000")
        text = text[:-1].strip()
    elif text.endswith("k"):
        multiplier = Decimal("1000")
        text = text[:-1].strip()
    try:
        return float(Decimal(text) * multiplier)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid narrative monetary value: {raw}") from exc


def _parse_percent(raw: str) -> float:
    return float(raw.replace("%", "").strip())


def _parse_integer(raw: str) -> int:
    return int(raw.replace(",", "").strip())


def _narrative_sources(workspace_id: str) -> list[dict[str, str]]:
    # Lazy import avoids forcing grantbot.master package initialization when
    # budget helpers are imported by independent test modules.
    from grantbot.master.database import list_revisions

    revisions = list_revisions(workspace_id)
    latest: dict[str, dict[str, Any]] = {}
    for item in revisions:
        task_id = str(item.get("task_id", ""))
        if not task_id:
            continue
        current = latest.get(task_id)
        if current is None or int(item.get("version", 0)) > int(
            current.get("version", 0)
        ):
            latest[task_id] = item
    if latest:
        return [
            {
                "source": f"revision:{item.get('revision_id', '')}",
                "text": str(item.get("content", "")),
            }
            for _, item in sorted(latest.items())
            if str(item.get("content", "")).strip()
        ]
    workspace = get_workspace(workspace_id)
    return [
        {
            "source": f"v17-task:{item.get('task_id', '')}",
            "text": str(item.get("response", "")),
        }
        for item in workspace.get("writer_tasks", [])
        if str(item.get("response", "")).strip()
    ]


def _extract_anchors(workspace_id: str) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for source in _narrative_sources(workspace_id):
        text = source["text"]
        for metric, patterns in MONEY_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    anchors.append(
                        {
                            "metric": metric,
                            "value": _parse_money(match.group("value")),
                            "raw": match.group("value").strip(),
                            "source": source["source"],
                            "context": match.group(0)[:240],
                        }
                    )
        for pattern in RATE_PATTERNS:
            for match in pattern.finditer(text):
                anchors.append(
                    {
                        "metric": "indirect_rate_percent",
                        "value": _parse_percent(match.group("value")),
                        "raw": match.group("value").strip(),
                        "source": source["source"],
                        "context": match.group(0)[:240],
                    }
                )
        for metric, patterns in COUNT_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    anchors.append(
                        {
                            "metric": metric,
                            "value": _parse_integer(match.group("value")),
                            "raw": match.group("value").strip(),
                            "source": source["source"],
                            "context": match.group(0)[:240],
                        }
                    )
    unique: dict[tuple[str, float, str, str], dict[str, Any]] = {}
    for item in anchors:
        key = (
            str(item["metric"]),
            float(item["value"]),
            str(item["source"]),
            str(item["context"]),
        )
        unique[key] = item
    return list(unique.values())


def _budget_requirement_state(workspace_id: str) -> tuple[bool, bool, list[str]]:
    from grantbot.compliance.requirements import requirement_rows

    rows = requirement_rows(workspace_id)
    budget_rows = [
        row for row in rows if str(row.get("category")) == "BUDGET"
    ]
    match_rows = [
        row for row in rows if str(row.get("category")) == "MATCH"
    ]
    budget_required = any(
        row["requirement_level"] == "MANDATORY"
        or (
            row["requirement_level"] == "CONDITIONAL"
            and row["status"] == "SATISFIED"
        )
        for row in budget_rows
    )
    match_positive_rows = [
        row
        for row in match_rows
        if not NO_MATCH_RE.search(str(row.get("requirement_text", "")))
    ]
    match_required = any(
        row["requirement_level"] == "MANDATORY"
        or (
            row["requirement_level"] == "CONDITIONAL"
            and row["status"] == "SATISFIED"
        )
        for row in match_positive_rows
    )
    notes = [str(row.get("requirement_text", "")) for row in budget_rows]
    return budget_required, match_required, notes


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _close_money(actual: float, expected: float) -> bool:
    tolerance = max(1.0, abs(expected) * 0.001)
    return abs(actual - expected) <= tolerance


def budget_consistency(
    workspace_id: str,
    *,
    require_approval: bool = True,
) -> dict[str, Any]:
    workspace = get_workspace(workspace_id)
    latest = latest_budget(workspace_id)
    budget_required, match_required, requirement_notes = (
        _budget_requirement_state(workspace_id)
    )
    blueprint = (workspace.get("analysis") or {}).get("blueprint") or {}
    if not budget_required and blueprint.get("budget_requirements"):
        budget_required = True
        requirement_notes.extend(
            str(item) for item in blueprint.get("budget_requirements", [])
        )

    blockers: list[str] = []
    warnings: list[str] = []
    comparisons: list[dict[str, Any]] = []
    if latest is None:
        if budget_required:
            blockers.append("Authoritative application requirements require a saved budget")
        return {
            "workspace_id": workspace_id,
            "budget_required": budget_required,
            "match_required": match_required,
            "latest_budget": None,
            "approved": False,
            "anchors": [],
            "comparisons": [],
            "requirement_notes": requirement_notes,
            "blockers": blockers,
            "warnings": warnings,
            "ready": not blockers,
            "submission_enabled": False,
        }

    calculation = latest["calculation"]
    expected = {
        "grant_request": float(calculation["grant_request"]),
        "total_project_cost": float(calculation["total_project_cost"]),
        "cash_match": float(calculation["cash_match"]),
        "in_kind_match": float(calculation["in_kind_match"]),
        "indirect_rate_percent": float(calculation["indirect_rate_percent"]),
        "participant_count": calculation.get("participant_count"),
        "housing_unit_count": calculation.get("housing_unit_count"),
    }

    ceiling = _number(blueprint.get("award_ceiling"))
    floor = _number(blueprint.get("award_floor"))
    grant_request = float(calculation["grant_request"])
    if ceiling is not None and grant_request > ceiling + 0.01:
        blockers.append(
            f"Grant request ${grant_request:,.2f} exceeds award ceiling ${ceiling:,.2f}"
        )
    if floor is not None and grant_request + 0.01 < floor:
        blockers.append(
            f"Grant request ${grant_request:,.2f} is below award floor ${floor:,.2f}"
        )
    if match_required and (
        float(calculation["cash_match"]) + float(calculation["in_kind_match"])
        <= 0
    ):
        blockers.append(
            "Applicable match/cost-sharing requirement has no cash or in-kind match in the budget"
        )
    if budget_required and require_approval and not latest["approved"]:
        blockers.append("Latest budget version lacks financial approval")

    anchors = _extract_anchors(workspace_id)
    for anchor in anchors:
        metric = str(anchor["metric"])
        target = expected.get(metric)
        if target is None:
            warnings.append(
                f"Narrative states {metric}={anchor['raw']} but the budget has no corresponding value"
            )
            continue
        actual = float(anchor["value"])
        target_value = float(target)
        if metric == "indirect_rate_percent":
            consistent = abs(actual - target_value) <= 0.05
        elif metric in {"participant_count", "housing_unit_count"}:
            consistent = int(round(actual)) == int(round(target_value))
        else:
            consistent = _close_money(actual, target_value)
        comparison = {
            **anchor,
            "budget_value": target,
            "consistent": consistent,
        }
        comparisons.append(comparison)
        if not consistent:
            blockers.append(
                f"Narrative {metric} {anchor['raw']} in {anchor['source']} "
                f"does not match budget value {target}"
            )

    grouped: dict[str, set[float]] = {}
    for anchor in anchors:
        grouped.setdefault(str(anchor["metric"]), set()).add(
            float(anchor["value"])
        )
    for metric, values in grouped.items():
        if len(values) > 1:
            blockers.append(
                f"Narratives contain conflicting values for {metric}: "
                + ", ".join(str(value) for value in sorted(values))
            )

    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    return {
        "workspace_id": workspace_id,
        "budget_required": budget_required,
        "match_required": match_required,
        "latest_budget": latest,
        "approved": bool(latest["approved"]),
        "award_floor": floor,
        "award_ceiling": ceiling,
        "anchors": anchors,
        "comparisons": comparisons,
        "requirement_notes": list(dict.fromkeys(requirement_notes)),
        "blockers": blockers,
        "warnings": warnings,
        "ready": not blockers,
        "submission_enabled": False,
    }
