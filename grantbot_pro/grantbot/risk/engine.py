from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any

from grantbot.core.database import connection, utc_now


METHODOLOGY_NOTE = (
    "The GrantBot risk index is an evidence-calibrated operational decision score, "
    "not an award probability, insurance probability, or prediction of funder behavior. "
    "It measures controllable application risk, uncertainty, and unresolved dependencies."
)


@dataclass(frozen=True, slots=True)
class RiskFactor:
    name: str
    score: int
    weight: float
    weighted_score: float
    evidence: list[str]
    controls: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    assessment_id: str
    workspace_id: str
    opportunity_id: str
    version: int
    risk_index: int
    confidence_score: int
    risk_band: str
    decision: str
    hard_blockers: list[str]
    controls: list[str]
    factors: list[RiskFactor]
    inputs: dict[str, Any]
    methodology_note: str
    created_by: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["factors"] = [factor.to_dict() for factor in self.factors]
        return result


def initialize_risk_schema() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS opportunity_risk_assessments (
                assessment_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                opportunity_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                input_sha256 TEXT NOT NULL,
                inputs_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                risk_index INTEGER NOT NULL,
                confidence_score INTEGER NOT NULL,
                risk_band TEXT NOT NULL,
                decision TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(workspace_id, version)
            );

            CREATE INDEX IF NOT EXISTS idx_opportunity_risk_workspace
                ON opportunity_risk_assessments(workspace_id, version DESC);

            CREATE INDEX IF NOT EXISTS idx_opportunity_risk_opportunity
                ON opportunity_risk_assessments(opportunity_id, created_at DESC);
            """
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


def _clamp(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _safe_int(value: Any, default: int) -> int:
    try:
        return _clamp(float(value))
    except (TypeError, ValueError):
        return default


def _risk_band(score: int) -> str:
    if score >= 70:
        return "CRITICAL"
    if score >= 45:
        return "HIGH"
    if score >= 25:
        return "MODERATE"
    return "LOW"


def _decision(score: int, hard_blockers: list[str]) -> str:
    fatal = any(
        marker in blocker.casefold()
        for blocker in hard_blockers
        for marker in (
            "ineligible",
            "deadline has passed",
        )
    )
    if fatal:
        return "REJECT"
    if hard_blockers or score >= 70:
        return "HOLD"
    if score >= 35:
        return "PROCEED_WITH_CONTROLS"
    return "PROCEED"


def _parse_deadline(value: Any) -> date | None:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%B %d, %Y",
        "%b %d, %Y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _days_to_deadline(value: Any, *, today: date | None = None) -> int | None:
    parsed = _parse_deadline(value)
    if parsed is None:
        return None
    current = today or datetime.now(timezone.utc).date()
    return (parsed - current).days


def _eligibility_factor(role: str, blockers: list[str]) -> tuple[int, list[str], list[str]]:
    normalized = role.strip().upper()
    evidence: list[str] = []
    controls: list[str] = []
    if blockers:
        evidence.extend(blockers)
    if normalized in {"REJECT", "INELIGIBLE"}:
        return 100, evidence or ["Applicant role is ineligible."], [
            "Do not invest drafting resources unless eligibility changes through an authoritative amendment."
        ]
    if normalized == "VERIFY":
        return 75, evidence or ["Applicant eligibility requires verification."], [
            "Resolve eligibility against the authoritative NOFO before advancing the application."
        ]
    if normalized == "PARTNER_OR_SUBRECIPIENT":
        return 55, evidence or ["A prime applicant or formal partner is required."], [
            "Document the prime applicant, role allocation, and submission responsibility before final review."
        ]
    if normalized == "DIRECT_APPLICANT":
        return 5, evidence or ["Applicant is classified as a direct applicant."], []
    return 60, evidence or ["Applicant-role classification is unavailable."], [
        "Complete authoritative applicant-eligibility review."
    ]


def _evidence_factor(acquisition_status: str, requirement_count: int) -> tuple[int, list[str], list[str]]:
    status = acquisition_status.strip().upper()
    if status == "FULL_NOFO_VALIDATED" and requirement_count > 0:
        return 5, ["Authoritative NOFO extraction is validated and requirements are indexed."], []
    if status == "FULL_NOFO_VALIDATED":
        return 35, ["NOFO is validated, but no authoritative requirements are indexed."], [
            "Synchronize authoritative requirements before relying on the extraction."
        ]
    if status:
        return 65, [f"NOFO acquisition status is {status}."], [
            "Validate the primary NOFO and amendments before final compliance review."
        ]
    return 85, ["Authoritative NOFO validation status is unavailable."], [
        "Acquire and validate the primary NOFO, amendments, instructions, and official forms."
    ]


def _requirement_factor(summary: dict[str, Any]) -> tuple[int, list[str], list[str], list[str]]:
    count = int(summary.get("requirement_count", 0) or 0)
    blocking = int(summary.get("blocking_count", 0) or 0)
    evidence = [f"{count} authoritative requirement(s) indexed; {blocking} blocking."]
    controls: list[str] = []
    hard: list[str] = []
    if count == 0:
        controls.append("Index and review authoritative requirements before submission readiness is asserted.")
        return 75, evidence, controls, hard
    if blocking:
        hard.append(f"{blocking} authoritative mandatory/conditional requirement(s) remain unresolved")
        controls.append("Resolve each blocking requirement with source-traceable evidence and authorized review.")
        return _clamp(35 + blocking * 12), evidence, controls, hard
    return 5, evidence, controls, hard


def _financial_factor(gate: dict[str, Any]) -> tuple[int, list[str], list[str], list[str]]:
    budget_required = bool(gate.get("budget_required"))
    match_required = bool(gate.get("match_required"))
    latest = gate.get("latest_budget")
    approved = bool(gate.get("approved"))
    blockers = [str(item) for item in gate.get("blockers", [])]
    warnings = [str(item) for item in gate.get("warnings", [])]
    evidence = [
        f"budget_required={budget_required}",
        f"match_required={match_required}",
        f"budget_saved={latest is not None}",
        f"budget_approved={approved}",
    ]
    evidence.extend(blockers)
    evidence.extend(warnings)
    controls: list[str] = []
    hard: list[str] = []
    if blockers:
        hard.extend(f"financial consistency: {item}" for item in blockers)
        controls.append("Reconcile the approved budget, narrative amounts, match, indirect rate, and NOFO limits.")
        return _clamp(45 + 10 * len(blockers)), evidence, controls, hard
    if budget_required and latest is None:
        hard.append("authoritative requirements require a budget but no budget is saved")
        controls.append("Create and review a deterministic workspace budget.")
        return 90, evidence, controls, hard
    if latest is not None and not approved:
        controls.append("Obtain authorized financial approval for the current immutable budget version.")
        return 45, evidence, controls, hard
    if match_required:
        return 20, evidence, controls, hard
    return 5, evidence, controls, hard


def _deadline_factor(days: int | None) -> tuple[int, list[str], list[str], list[str]]:
    if days is None:
        return 45, ["Submission deadline could not be normalized."], [
            "Confirm the authoritative submission deadline and timezone."
        ], []
    evidence = [f"{days} day(s) remain until the normalized deadline."]
    if days < 0:
        return 100, evidence, [], ["submission deadline has passed"]
    if days <= 3:
        return 95, evidence, ["Use executive escalation and a same-day completion plan."], []
    if days <= 7:
        return 80, evidence, ["Freeze scope and prioritize only submission-critical work."], []
    if days <= 14:
        return 60, evidence, ["Lock the review calendar and resolve external dependencies immediately."], []
    if days <= 30:
        return 35, evidence, ["Track dependencies daily until all blocking items are cleared."], []
    if days <= 60:
        return 18, evidence, [], []
    return 8, evidence, [], []


def calculate_risk(inputs: dict[str, Any]) -> dict[str, Any]:
    role = str(inputs.get("applicant_role") or "")
    eligibility_blockers = [str(item) for item in inputs.get("eligibility_blockers", [])]
    eligibility = _eligibility_factor(role, eligibility_blockers)
    evidence_authority = _evidence_factor(
        str(inputs.get("acquisition_status") or ""),
        int(inputs.get("requirement_count", 0) or 0),
    )
    requirements = _requirement_factor(
        {
            "requirement_count": inputs.get("requirement_count", 0),
            "blocking_count": inputs.get("blocking_requirement_count", 0),
        }
    )
    financial = _financial_factor(
        {
            "budget_required": inputs.get("budget_required", False),
            "match_required": inputs.get("match_required", False),
            "latest_budget": inputs.get("latest_budget"),
            "approved": inputs.get("budget_approved", False),
            "blockers": inputs.get("budget_blockers", []),
            "warnings": inputs.get("budget_warnings", []),
        }
    )
    deadline = _deadline_factor(inputs.get("days_to_deadline"))

    readiness_score = _safe_int(inputs.get("readiness_score"), 0)
    competitive_score = _safe_int(inputs.get("competitive_score"), 0)
    open_risks = max(0, int(inputs.get("open_risk_count", 0) or 0))
    pending_checklist = max(0, int(inputs.get("pending_checklist_count", 0) or 0))
    incomplete_drafts = max(0, int(inputs.get("incomplete_draft_count", 0) or 0))
    draft_count = max(0, int(inputs.get("draft_count", 0) or 0))

    readiness_factor = (
        100 - readiness_score,
        [f"Workspace readiness score is {readiness_score}/100."],
        ["Resolve readiness deficiencies before final review."] if readiness_score < 75 else [],
    )
    competitive_factor = (
        100 - competitive_score,
        [f"Competitive strength score is {competitive_score}/100."],
        ["Strengthen fit, differentiation, evidence, and reviewer alignment where feasible."]
        if competitive_score < 60
        else [],
    )
    backlog_score = _clamp(open_risks * 18 + pending_checklist * 6)
    backlog_factor = (
        backlog_score,
        [f"{open_risks} open risk(s) and {pending_checklist} pending checklist item(s) remain."],
        ["Close documented risks and checklist dependencies with named evidence and reviewers."]
        if backlog_score
        else [],
    )
    if draft_count == 0:
        narrative_score = 65
    else:
        narrative_score = _clamp((incomplete_drafts / draft_count) * 100)
    narrative_factor = (
        narrative_score,
        [f"{incomplete_drafts} of {draft_count} narrative task(s) are incomplete or not review-ready."],
        ["Complete and review all required narrative tasks against authoritative prompts."]
        if incomplete_drafts
        else [],
    )

    factor_specs: list[tuple[str, float, tuple[Any, ...]]] = [
        ("eligibility", 0.18, eligibility),
        ("evidence_authority", 0.14, evidence_authority),
        ("authoritative_requirements", 0.16, requirements[:3]),
        ("financial_consistency", 0.14, financial[:3]),
        ("deadline_pressure", 0.12, deadline[:3]),
        ("operational_readiness", 0.10, readiness_factor),
        ("competitive_uncertainty", 0.08, competitive_factor),
        ("review_backlog", 0.04, backlog_factor),
        ("narrative_completion", 0.04, narrative_factor),
    ]

    factors: list[RiskFactor] = []
    for name, weight, spec in factor_specs:
        score = _clamp(float(spec[0]))
        evidence_items = [str(item) for item in spec[1]]
        controls = [str(item) for item in spec[2]]
        factors.append(
            RiskFactor(
                name=name,
                score=score,
                weight=weight,
                weighted_score=round(score * weight, 2),
                evidence=evidence_items,
                controls=controls,
            )
        )

    hard_blockers: list[str] = []
    hard_blockers.extend(str(item) for item in requirements[3])
    hard_blockers.extend(str(item) for item in financial[3])
    hard_blockers.extend(str(item) for item in deadline[3])
    fatal_role = role.strip().upper() in {"REJECT", "INELIGIBLE"}
    if fatal_role:
        hard_blockers.extend(eligibility_blockers)
        hard_blockers.append("applicant is ineligible")
    hard_blockers = list(dict.fromkeys(item for item in hard_blockers if item))

    controls = list(
        dict.fromkeys(
            control
            for factor in factors
            for control in factor.controls
            if control
        )
    )
    risk_index = _clamp(sum(factor.weighted_score for factor in factors))
    fatal_deadline = any(
        "deadline has passed" in blocker.casefold()
        for blocker in hard_blockers
    )
    if fatal_role or fatal_deadline:
        risk_index = max(risk_index, 95)
    elif hard_blockers:
        risk_index = max(risk_index, 70)

    availability = {
        "applicant_role": bool(role.strip()),
        "authoritative_nofo_status": bool(str(inputs.get("acquisition_status") or "").strip()),
        "authoritative_requirements": int(inputs.get("requirement_count", 0) or 0) > 0,
        "deadline": inputs.get("days_to_deadline") is not None,
        "readiness": inputs.get("readiness_score") is not None,
        "competitive": inputs.get("competitive_score") is not None,
        "budget_gate": "budget_required" in inputs,
        "review_state": "open_risk_count" in inputs and "pending_checklist_count" in inputs,
        "narratives": "draft_count" in inputs,
    }
    confidence_score = _clamp(
        100 * sum(1 for present in availability.values() if present) / len(availability)
    )

    return {
        "risk_index": risk_index,
        "confidence_score": confidence_score,
        "risk_band": _risk_band(risk_index),
        "decision": _decision(risk_index, hard_blockers),
        "hard_blockers": hard_blockers,
        "controls": controls,
        "factors": factors,
        "methodology_note": METHODOLOGY_NOTE,
    }


def _extract_deadline(workspace: dict[str, Any]) -> Any:
    analysis = workspace.get("analysis") or {}
    blueprint = analysis.get("blueprint") or {}
    for key in (
        "deadline",
        "close_date",
        "closing_date",
        "due_date",
        "submission_deadline",
    ):
        value = blueprint.get(key)
        if value:
            return value
    return None


def evaluate_workspace_risk(workspace_id: str) -> dict[str, Any]:
    from grantbot.budget.workspace import budget_consistency
    from grantbot.compliance.requirements import requirement_summary
    from grantbot.review.staging_v17 import get_workspace

    workspace = get_workspace(workspace_id)
    requirement_gate = requirement_summary(workspace_id)
    budget_gate = budget_consistency(workspace_id)
    analysis = workspace.get("analysis") or {}
    competitive = analysis.get("competitive_match") or {}
    applicant_role = competitive.get("applicant_role") or {}
    blueprint = analysis.get("blueprint") or {}

    open_risks = [
        item
        for item in workspace.get("risks", [])
        if str(item.get("status", "")).upper() == "OPEN"
    ]
    pending_checklist = [
        item
        for item in workspace.get("checklist", [])
        if str(item.get("status", "")).upper() == "PENDING"
    ]
    drafts = list(workspace.get("writer_tasks", []))
    incomplete = [
        item
        for item in drafts
        if str(item.get("status", "")).upper() not in {"READY_FOR_REVIEW", "APPROVED"}
        or not str(item.get("response", "")).strip()
    ]

    inputs = {
        "workspace_id": workspace_id,
        "opportunity_id": str(workspace.get("opportunity_id", "")),
        "applicant_role": str(applicant_role.get("role", "")),
        "eligibility_blockers": list(applicant_role.get("blockers", []) or competitive.get("blockers", []) or []),
        "acquisition_status": str(blueprint.get("acquisition_status", "")),
        "requirement_count": int(requirement_gate.get("requirement_count", 0) or 0),
        "blocking_requirement_count": int(requirement_gate.get("blocking_count", 0) or 0),
        "budget_required": bool(budget_gate.get("budget_required")),
        "match_required": bool(budget_gate.get("match_required")),
        "latest_budget": budget_gate.get("latest_budget"),
        "budget_approved": bool(budget_gate.get("approved")),
        "budget_blockers": list(budget_gate.get("blockers", [])),
        "budget_warnings": list(budget_gate.get("warnings", [])),
        "days_to_deadline": _days_to_deadline(_extract_deadline(workspace)),
        "readiness_score": workspace.get("readiness_score"),
        "competitive_score": workspace.get("competitive_score"),
        "open_risk_count": len(open_risks),
        "pending_checklist_count": len(pending_checklist),
        "draft_count": len(drafts),
        "incomplete_draft_count": len(incomplete),
        "stage": str(workspace.get("stage", "")),
        "human_approved": bool(workspace.get("human_approved")),
    }
    result = calculate_risk(inputs)
    result["inputs"] = inputs
    return result


def _next_version(workspace_id: str) -> int:
    initialize_risk_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS current_version "
            "FROM opportunity_risk_assessments WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
    return int(row["current_version"]) + 1


def assess_workspace_risk(workspace_id: str, *, actor: str) -> RiskAssessment:
    actor = " ".join(str(actor).split()).strip()
    if not actor:
        raise ValueError("actor is required")
    evaluated = evaluate_workspace_risk(workspace_id)
    inputs = dict(evaluated.pop("inputs"))
    version = _next_version(workspace_id)
    created_at = utc_now()
    assessment = RiskAssessment(
        assessment_id=uuid.uuid4().hex,
        workspace_id=workspace_id,
        opportunity_id=str(inputs.get("opportunity_id", "")),
        version=version,
        risk_index=int(evaluated["risk_index"]),
        confidence_score=int(evaluated["confidence_score"]),
        risk_band=str(evaluated["risk_band"]),
        decision=str(evaluated["decision"]),
        hard_blockers=list(evaluated["hard_blockers"]),
        controls=list(evaluated["controls"]),
        factors=list(evaluated["factors"]),
        inputs=inputs,
        methodology_note=METHODOLOGY_NOTE,
        created_by=actor,
        created_at=created_at,
    )
    payload = assessment.to_dict()
    initialize_risk_schema()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO opportunity_risk_assessments(
                assessment_id, workspace_id, opportunity_id, version,
                input_sha256, inputs_json, result_json, risk_index,
                confidence_score, risk_band, decision, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assessment.assessment_id,
                workspace_id,
                assessment.opportunity_id,
                version,
                _sha(inputs),
                _canonical(inputs),
                _canonical(payload),
                assessment.risk_index,
                assessment.confidence_score,
                assessment.risk_band,
                assessment.decision,
                actor,
                created_at,
            ),
        )
    return assessment


def _decode_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    try:
        payload = json.loads(str(item.get("result_json", "{}")))
    except json.JSONDecodeError:
        payload = {}
    payload["input_sha256"] = str(item.get("input_sha256", ""))
    return payload


def latest_risk(workspace_id: str) -> dict[str, Any] | None:
    initialize_risk_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM opportunity_risk_assessments "
            "WHERE workspace_id=? ORDER BY version DESC LIMIT 1",
            (workspace_id,),
        ).fetchone()
    return None if row is None else _decode_row(row)


def risk_history(workspace_id: str) -> list[dict[str, Any]]:
    initialize_risk_schema()
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM opportunity_risk_assessments "
            "WHERE workspace_id=? ORDER BY version DESC",
            (workspace_id,),
        ).fetchall()
    return [_decode_row(row) for row in rows]
