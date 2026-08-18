from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


LIFECYCLE = (
    "DISCOVERED",
    "ELIGIBILITY_CHECKED",
    "SCORED",
    "DRAFTING",
    "READY_FOR_REVIEW",
    "APPROVED",
    "READY_FOR_SUBMISSION",
    "SUBMITTED",
)

TRANSITIONS: dict[str, set[str]] = {
    "DRAFTING": {"READY_FOR_REVIEW"},
    "READY_FOR_REVIEW": {"DRAFTING", "APPROVED"},
    "APPROVED": {"DRAFTING", "READY_FOR_SUBMISSION"},
    "READY_FOR_SUBMISSION": {"DRAFTING"},
}

DRAFT_STATUSES = {"NEEDS_DRAFT", "DRAFT", "READY_FOR_REVIEW", "APPROVED"}
CHECKLIST_STATUSES = {"PENDING", "VERIFIED", "NOT_APPLICABLE"}


@dataclass(frozen=True, slots=True)
class WriterTask:
    task_id: str
    ordinal: int
    question: str
    category: str
    evidence_requirements: list[str]
    strategy: list[str]
    status: str
    version: int
    response: str
    provenance: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkspaceSummary:
    workspace_id: str
    opportunity_id: str
    title: str
    funder: str
    stage: str
    readiness_score: int
    competitive_score: int
    writer_task_count: int
    drafts_complete: int
    unresolved_risks: int
    pending_checklist_items: int
    human_approved: bool
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _db_path() -> Path:
    configured = os.getenv("GRANTBOT_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _root() / "data" / "grantbot.db"


@contextmanager
def _connect() -> Iterable[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        yield connection
    finally:
        connection.close()


def initialize_schema() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS application_staging_v17 (
                workspace_id TEXT PRIMARY KEY,
                opportunity_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                funder TEXT NOT NULL,
                stage TEXT NOT NULL,
                readiness_score INTEGER NOT NULL,
                competitive_score INTEGER NOT NULL,
                human_approved INTEGER NOT NULL DEFAULT 0,
                approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT NOT NULL DEFAULT '',
                analysis_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS application_drafts_v17 (
                task_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                question TEXT NOT NULL,
                category TEXT NOT NULL,
                evidence_requirements_json TEXT NOT NULL,
                strategy_json TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                response TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id)
                    REFERENCES application_staging_v17(workspace_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS application_risks_v17 (
                risk_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                risk_text TEXT NOT NULL,
                status TEXT NOT NULL,
                resolution_note TEXT NOT NULL,
                resolved_by TEXT NOT NULL,
                resolved_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id)
                    REFERENCES application_staging_v17(workspace_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS application_checklist_v17 (
                checklist_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                item_type TEXT NOT NULL,
                item_text TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id)
                    REFERENCES application_staging_v17(workspace_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS application_review_events_v17 (
                event_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_stage TEXT NOT NULL,
                to_stage TEXT NOT NULL,
                actor TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id)
                    REFERENCES application_staging_v17(workspace_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_drafts_workspace_v17
                ON application_drafts_v17(workspace_id, ordinal);
            CREATE INDEX IF NOT EXISTS idx_risks_workspace_v17
                ON application_risks_v17(workspace_id, status);
            CREATE INDEX IF NOT EXISTS idx_checklist_workspace_v17
                ON application_checklist_v17(workspace_id, status);
            CREATE INDEX IF NOT EXISTS idx_events_workspace_v17
                ON application_review_events_v17(workspace_id, created_at);
            """
        )
        connection.commit()


def _json_load(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = _safe_text(item)
        if text and text not in output:
            output.append(text)
    return output


def _validate_identifier(value: str, label: str) -> str:
    value = _safe_text(value)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", value) or ".." in value:
        raise ValueError(f"Invalid {label}")
    return value


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _existing_analysis(opportunity_id: str) -> dict[str, Any] | None:
    root = _root()
    blueprint = _read_json(
        root / "data" / "nofo_blueprints" / opportunity_id / "application_blueprint.json"
    )
    competitive = _read_json(
        root / "data" / "matching" / opportunity_id / "competitive_match.json"
    )
    readiness = _read_json(
        root / "data" / "readiness" / opportunity_id / "compliance_readiness.json"
    )
    if blueprint is None or competitive is None or readiness is None:
        return None
    return {
        "opportunity_id": opportunity_id,
        "promoted_at": _utc_now(),
        "analysis_source": "EXISTING_V13_V15_OUTPUTS",
        "blueprint": blueprint,
        "competitive_match": competitive,
        "readiness": readiness,
    }


def load_or_promote_analysis(
    opportunity_id: str,
    *,
    manual_urls: list[str] | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    opportunity_id = _validate_identifier(opportunity_id, "opportunity_id")
    if not refresh:
        existing = _existing_analysis(opportunity_id)
        if existing is not None:
            return existing

    from grantbot.pipeline.live_queue_v16 import promote_opportunity

    promoted = promote_opportunity(
        opportunity_id,
        manual_urls=manual_urls or [],
    )
    promoted["analysis_source"] = "V16_PROMOTION"
    return promoted


def _classify_question(question: str) -> tuple[str, list[str], list[str]]:
    lower = question.lower()
    if any(term in lower for term in ("budget", "cost", "fund", "match", "financial")):
        return (
            "BUDGET_FINANCE",
            [
                "Use only verified or explicitly labeled projected financial figures.",
                "Reconcile every amount with the application budget and match requirements.",
            ],
            [
                "Lead with cost effectiveness and capital efficiency.",
                "Tie requested dollars to concrete outputs and measurable outcomes.",
            ],
        )
    if any(term in lower for term in ("outcome", "measure", "evaluate", "performance", "success")):
        return (
            "OUTCOMES_EVALUATION",
            [
                "Use traceable baseline, target, measurement method, and reporting frequency.",
                "Do not present projected outcomes as achieved results.",
            ],
            [
                "Connect activities to measurable participant and community outcomes.",
                "Use reviewer-friendly metrics and explicit accountability language.",
            ],
        )
    if any(term in lower for term in ("organization", "capacity", "experience", "staff", "board")):
        return (
            "ORGANIZATIONAL_CAPACITY",
            [
                "Use verified governance, leadership, registration, and operating facts.",
                "Flag unverified staffing, partnership, or historical claims instead of guessing.",
            ],
            [
                "Establish stewardship, governance, controls, and implementation readiness.",
                "Align organizational strengths directly with the funder's scoring criteria.",
            ],
        )
    if any(term in lower for term in ("need", "problem", "community", "population", "homeless", "reentry")):
        return (
            "NEEDS_STATEMENT",
            [
                "Use current, geographically relevant, source-traceable statistics.",
                "Distinguish Broken Growth program facts from external community data.",
            ],
            [
                "Use ethos-pathos-logos without exploiting beneficiaries.",
                "Quantify the cost of inaction only when a defensible source supports it.",
            ],
        )
    if any(term in lower for term in ("sustain", "continue", "future", "long-term")):
        return (
            "SUSTAINABILITY",
            [
                "Use realistic, supportable revenue and partnership assumptions.",
                "Identify dependencies that require founder, board, or funder confirmation.",
            ],
            [
                "Show diversified funding, operating discipline, and replication potential.",
                "Avoid implying commitments from partners that are not documented.",
            ],
        )
    return (
        "PROGRAM_NARRATIVE",
        [
            "Answer the exact funder question and preserve all stated constraints.",
            "Use only verified organizational facts or clearly labeled projections.",
        ],
        [
            "Mirror the funder's terminology and scoring priorities.",
            "Use specific problem-solution-impact logic and measurable implementation language.",
        ],
    )


def _build_writer_tasks(questions: Iterable[str]) -> list[WriterTask]:
    tasks: list[WriterTask] = []
    for ordinal, question in enumerate(questions, start=1):
        clean = _safe_text(question)
        if not clean:
            continue
        category, evidence, strategy = _classify_question(clean)
        task_id = _stable_id("task", str(ordinal), clean)
        tasks.append(
            WriterTask(
                task_id=task_id,
                ordinal=ordinal,
                question=clean,
                category=category,
                evidence_requirements=evidence,
                strategy=strategy,
                status="NEEDS_DRAFT",
                version=1,
                response="",
                provenance=[],
            )
        )
    return tasks


def _seed_risks(connection: sqlite3.Connection, workspace_id: str, analysis: dict[str, Any]) -> None:
    readiness = analysis.get("readiness") or {}
    competitive = analysis.get("competitive_match") or {}
    risk_texts = _safe_list(readiness.get("compliance_risks")) + _safe_list(competitive.get("blockers"))
    for risk in dict.fromkeys(risk_texts):
        risk_id = _stable_id("risk", workspace_id, risk)
        connection.execute(
            """
            INSERT OR IGNORE INTO application_risks_v17 (
                risk_id, workspace_id, risk_text, status, resolution_note,
                resolved_by, resolved_at, created_at
            ) VALUES (?, ?, ?, 'OPEN', '', '', '', ?)
            """,
            (risk_id, workspace_id, risk, _utc_now()),
        )


def _seed_checklist(connection: sqlite3.Connection, workspace_id: str, analysis: dict[str, Any]) -> None:
    blueprint = analysis.get("blueprint") or {}
    readiness = analysis.get("readiness") or {}
    entries: list[tuple[str, str]] = []
    for text in _safe_list(readiness.get("missing_items")):
        entries.append(("MISSING_INFORMATION", text))
    for text in _safe_list(readiness.get("required_attachments")):
        entries.append(("REQUIRED_ATTACHMENT", text))
    for text in _safe_list(blueprint.get("submission_requirements")):
        entries.append(("SUBMISSION_REQUIREMENT", text))
    for text in _safe_list(blueprint.get("match_requirements")):
        entries.append(("MATCH_REQUIREMENT", text))

    seen: set[tuple[str, str]] = set()
    for item_type, item_text in entries:
        key = (item_type, item_text)
        if key in seen:
            continue
        seen.add(key)
        checklist_id = _stable_id("check", workspace_id, item_type, item_text)
        now = _utc_now()
        connection.execute(
            """
            INSERT OR IGNORE INTO application_checklist_v17 (
                checklist_id, workspace_id, item_type, item_text, status,
                note, updated_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'PENDING', '', '', ?, ?)
            """,
            (checklist_id, workspace_id, item_type, item_text, now, now),
        )


def create_workspace(
    opportunity_id: str,
    *,
    manual_urls: list[str] | None = None,
    refresh_analysis: bool = False,
) -> dict[str, Any]:
    initialize_schema()
    opportunity_id = _validate_identifier(opportunity_id, "opportunity_id")

    with _connect() as connection:
        existing = connection.execute(
            "SELECT workspace_id FROM application_staging_v17 WHERE opportunity_id = ?",
            (opportunity_id,),
        ).fetchone()
    if existing is not None and not refresh_analysis:
        return get_workspace(str(existing["workspace_id"]))

    analysis = load_or_promote_analysis(
        opportunity_id,
        manual_urls=manual_urls,
        refresh=refresh_analysis,
    )
    blueprint = analysis.get("blueprint") or {}
    competitive = analysis.get("competitive_match") or {}
    readiness = analysis.get("readiness") or {}

    title = _safe_text(blueprint.get("title")) or _safe_text(competitive.get("title")) or opportunity_id
    funder = _safe_text(blueprint.get("funder")) or _safe_text(competitive.get("funder"))
    readiness_score = int(readiness.get("final_readiness_score") or 0)
    competitive_score = int(competitive.get("final_score") or 0)
    questions = _safe_list(blueprint.get("application_questions"))
    tasks = _build_writer_tasks(questions)
    now = _utc_now()

    with _connect() as connection:
        if existing is not None:
            workspace_id = str(existing["workspace_id"])
            connection.execute("DELETE FROM application_drafts_v17 WHERE workspace_id = ?", (workspace_id,))
            connection.execute("DELETE FROM application_risks_v17 WHERE workspace_id = ?", (workspace_id,))
            connection.execute("DELETE FROM application_checklist_v17 WHERE workspace_id = ?", (workspace_id,))
            connection.execute(
                """
                UPDATE application_staging_v17
                SET title = ?, funder = ?, stage = 'DRAFTING', readiness_score = ?,
                    competitive_score = ?, human_approved = 0, approved_by = '', approved_at = '',
                    analysis_json = ?, updated_at = ?
                WHERE workspace_id = ?
                """,
                (
                    title,
                    funder,
                    readiness_score,
                    competitive_score,
                    json.dumps(analysis, ensure_ascii=False),
                    now,
                    workspace_id,
                ),
            )
        else:
            workspace_id = uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO application_staging_v17 (
                    workspace_id, opportunity_id, title, funder, stage,
                    readiness_score, competitive_score, human_approved,
                    approved_by, approved_at, analysis_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'DRAFTING', ?, ?, 0, '', '', ?, ?, ?)
                """,
                (
                    workspace_id,
                    opportunity_id,
                    title,
                    funder,
                    readiness_score,
                    competitive_score,
                    json.dumps(analysis, ensure_ascii=False),
                    now,
                    now,
                ),
            )

        for task in tasks:
            connection.execute(
                """
                INSERT INTO application_drafts_v17 (
                    task_id, workspace_id, ordinal, question, category,
                    evidence_requirements_json, strategy_json, status, version,
                    response, provenance_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    workspace_id,
                    task.ordinal,
                    task.question,
                    task.category,
                    json.dumps(task.evidence_requirements, ensure_ascii=False),
                    json.dumps(task.strategy, ensure_ascii=False),
                    task.status,
                    task.version,
                    task.response,
                    json.dumps(task.provenance, ensure_ascii=False),
                    now,
                    now,
                ),
            )

        _seed_risks(connection, workspace_id, analysis)
        _seed_checklist(connection, workspace_id, analysis)
        connection.execute(
            """
            INSERT INTO application_review_events_v17 (
                event_id, workspace_id, event_type, from_stage, to_stage,
                actor, note, created_at
            ) VALUES (?, ?, 'WORKSPACE_CREATED', '', 'DRAFTING', 'system', ?, ?)
            """,
            (
                uuid.uuid4().hex,
                workspace_id,
                f"Opportunity {opportunity_id} staged from {analysis.get('analysis_source', 'analysis')}.",
                now,
            ),
        )
        connection.commit()

    _write_snapshot(workspace_id)
    return get_workspace(workspace_id)


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "task_id": str(row["task_id"]),
        "ordinal": int(row["ordinal"]),
        "question": str(row["question"]),
        "category": str(row["category"]),
        "evidence_requirements": _json_load(str(row["evidence_requirements_json"])) or [],
        "strategy": _json_load(str(row["strategy_json"])) or [],
        "status": str(row["status"]),
        "version": int(row["version"]),
        "response": str(row["response"]),
        "provenance": _json_load(str(row["provenance_json"])) or [],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def get_workspace(workspace_id: str) -> dict[str, Any]:
    initialize_schema()
    workspace_id = _validate_identifier(workspace_id, "workspace_id")
    with _connect() as connection:
        workspace = connection.execute(
            "SELECT * FROM application_staging_v17 WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if workspace is None:
            raise FileNotFoundError(f"Workspace not found: {workspace_id}")
        drafts = connection.execute(
            "SELECT * FROM application_drafts_v17 WHERE workspace_id = ? ORDER BY ordinal",
            (workspace_id,),
        ).fetchall()
        risks = connection.execute(
            "SELECT * FROM application_risks_v17 WHERE workspace_id = ? ORDER BY created_at, risk_id",
            (workspace_id,),
        ).fetchall()
        checklist = connection.execute(
            "SELECT * FROM application_checklist_v17 WHERE workspace_id = ? ORDER BY item_type, checklist_id",
            (workspace_id,),
        ).fetchall()
        events = connection.execute(
            "SELECT * FROM application_review_events_v17 WHERE workspace_id = ? ORDER BY created_at, event_id",
            (workspace_id,),
        ).fetchall()

    return {
        "workspace_id": str(workspace["workspace_id"]),
        "opportunity_id": str(workspace["opportunity_id"]),
        "title": str(workspace["title"]),
        "funder": str(workspace["funder"]),
        "stage": str(workspace["stage"]),
        "readiness_score": int(workspace["readiness_score"]),
        "competitive_score": int(workspace["competitive_score"]),
        "human_approved": bool(workspace["human_approved"]),
        "approved_by": str(workspace["approved_by"]),
        "approved_at": str(workspace["approved_at"]),
        "analysis": _json_load(str(workspace["analysis_json"])) or {},
        "writer_tasks": [_row_to_task(row) for row in drafts],
        "risks": [dict(row) for row in risks],
        "checklist": [dict(row) for row in checklist],
        "events": [dict(row) for row in events],
        "created_at": str(workspace["created_at"]),
        "updated_at": str(workspace["updated_at"]),
    }


def list_workspaces() -> list[dict[str, Any]]:
    initialize_schema()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM application_staging_v17 ORDER BY updated_at DESC"
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            workspace_id = str(row["workspace_id"])
            task_count = int(connection.execute(
                "SELECT COUNT(*) FROM application_drafts_v17 WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()[0])
            drafts_complete = int(connection.execute(
                "SELECT COUNT(*) FROM application_drafts_v17 WHERE workspace_id = ? AND status IN ('READY_FOR_REVIEW','APPROVED') AND length(trim(response)) > 0",
                (workspace_id,),
            ).fetchone()[0])
            unresolved_risks = int(connection.execute(
                "SELECT COUNT(*) FROM application_risks_v17 WHERE workspace_id = ? AND status = 'OPEN'",
                (workspace_id,),
            ).fetchone()[0])
            pending = int(connection.execute(
                "SELECT COUNT(*) FROM application_checklist_v17 WHERE workspace_id = ? AND status = 'PENDING'",
                (workspace_id,),
            ).fetchone()[0])
            summary = WorkspaceSummary(
                workspace_id=workspace_id,
                opportunity_id=str(row["opportunity_id"]),
                title=str(row["title"]),
                funder=str(row["funder"]),
                stage=str(row["stage"]),
                readiness_score=int(row["readiness_score"]),
                competitive_score=int(row["competitive_score"]),
                writer_task_count=task_count,
                drafts_complete=drafts_complete,
                unresolved_risks=unresolved_risks,
                pending_checklist_items=pending,
                human_approved=bool(row["human_approved"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            output.append(summary.to_dict())
    return output


def save_draft(
    workspace_id: str,
    task_id: str,
    *,
    response: str,
    status: str,
    provenance: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    initialize_schema()
    workspace_id = _validate_identifier(workspace_id, "workspace_id")
    task_id = _validate_identifier(task_id, "task_id")
    status = _safe_text(status).upper()
    if status not in DRAFT_STATUSES:
        raise ValueError(f"Invalid draft status: {status}")
    response = str(response).strip()
    if status in {"READY_FOR_REVIEW", "APPROVED"} and not response:
        raise ValueError("A non-empty response is required for review or approval")
    clean_provenance: list[dict[str, str]] = []
    for item in provenance or []:
        if not isinstance(item, dict):
            continue
        source = _safe_text(item.get("source"))
        note = _safe_text(item.get("note"))
        if source:
            clean_provenance.append({"source": source, "note": note})
    now = _utc_now()
    with _connect() as connection:
        row = connection.execute(
            "SELECT version FROM application_drafts_v17 WHERE workspace_id = ? AND task_id = ?",
            (workspace_id, task_id),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Draft task not found: {task_id}")
        version = int(row["version"]) + 1
        connection.execute(
            """
            UPDATE application_drafts_v17
            SET response = ?, status = ?, version = ?, provenance_json = ?, updated_at = ?
            WHERE workspace_id = ? AND task_id = ?
            """,
            (
                response,
                status,
                version,
                json.dumps(clean_provenance, ensure_ascii=False),
                now,
                workspace_id,
                task_id,
            ),
        )
        connection.execute(
            "UPDATE application_staging_v17 SET human_approved = 0, approved_by = '', approved_at = '', stage = 'DRAFTING', updated_at = ? WHERE workspace_id = ?",
            (now, workspace_id),
        )
        connection.execute(
            """
            INSERT INTO application_review_events_v17 (
                event_id, workspace_id, event_type, from_stage, to_stage, actor, note, created_at
            ) VALUES (?, ?, 'DRAFT_UPDATED', '', 'DRAFTING', 'writer', ?, ?)
            """,
            (uuid.uuid4().hex, workspace_id, f"Draft task {task_id} updated to version {version}.", now),
        )
        connection.commit()
    _write_snapshot(workspace_id)
    return get_workspace(workspace_id)


def update_checklist_item(
    workspace_id: str,
    checklist_id: str,
    *,
    status: str,
    actor: str,
    note: str = "",
) -> dict[str, Any]:
    initialize_schema()
    workspace_id = _validate_identifier(workspace_id, "workspace_id")
    checklist_id = _validate_identifier(checklist_id, "checklist_id")
    status = _safe_text(status).upper()
    actor = _safe_text(actor)
    note = _safe_text(note)
    if status not in CHECKLIST_STATUSES:
        raise ValueError(f"Invalid checklist status: {status}")
    if not actor:
        raise ValueError("actor is required")
    if status == "NOT_APPLICABLE" and not note:
        raise ValueError("A note is required when marking an item NOT_APPLICABLE")
    now = _utc_now()
    with _connect() as connection:
        current = connection.execute(
            "SELECT checklist_id FROM application_checklist_v17 WHERE workspace_id = ? AND checklist_id = ?",
            (workspace_id, checklist_id),
        ).fetchone()
        if current is None:
            raise FileNotFoundError(f"Checklist item not found: {checklist_id}")
        connection.execute(
            """
            UPDATE application_checklist_v17
            SET status = ?, note = ?, updated_by = ?, updated_at = ?
            WHERE workspace_id = ? AND checklist_id = ?
            """,
            (status, note, actor, now, workspace_id, checklist_id),
        )
        connection.execute(
            "UPDATE application_staging_v17 SET updated_at = ? WHERE workspace_id = ?",
            (now, workspace_id),
        )
        connection.commit()
    _write_snapshot(workspace_id)
    return get_workspace(workspace_id)


def resolve_risk(
    workspace_id: str,
    risk_id: str,
    *,
    actor: str,
    resolution_note: str,
) -> dict[str, Any]:
    initialize_schema()
    workspace_id = _validate_identifier(workspace_id, "workspace_id")
    risk_id = _validate_identifier(risk_id, "risk_id")
    actor = _safe_text(actor)
    resolution_note = _safe_text(resolution_note)
    if not actor or not resolution_note:
        raise ValueError("actor and resolution_note are required")
    now = _utc_now()
    with _connect() as connection:
        current = connection.execute(
            "SELECT risk_id FROM application_risks_v17 WHERE workspace_id = ? AND risk_id = ?",
            (workspace_id, risk_id),
        ).fetchone()
        if current is None:
            raise FileNotFoundError(f"Risk not found: {risk_id}")
        connection.execute(
            """
            UPDATE application_risks_v17
            SET status = 'RESOLVED', resolution_note = ?, resolved_by = ?, resolved_at = ?
            WHERE workspace_id = ? AND risk_id = ?
            """,
            (resolution_note, actor, now, workspace_id, risk_id),
        )
        connection.execute(
            "UPDATE application_staging_v17 SET updated_at = ? WHERE workspace_id = ?",
            (now, workspace_id),
        )
        connection.commit()
    _write_snapshot(workspace_id)
    return get_workspace(workspace_id)


def _gate_state(connection: sqlite3.Connection, workspace_id: str) -> dict[str, Any]:
    task_total = int(connection.execute(
        "SELECT COUNT(*) FROM application_drafts_v17 WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchone()[0])
    task_ready = int(connection.execute(
        "SELECT COUNT(*) FROM application_drafts_v17 WHERE workspace_id = ? AND status IN ('READY_FOR_REVIEW','APPROVED') AND length(trim(response)) > 0",
        (workspace_id,),
    ).fetchone()[0])
    open_risks = int(connection.execute(
        "SELECT COUNT(*) FROM application_risks_v17 WHERE workspace_id = ? AND status = 'OPEN'",
        (workspace_id,),
    ).fetchone()[0])
    pending_checklist = int(connection.execute(
        "SELECT COUNT(*) FROM application_checklist_v17 WHERE workspace_id = ? AND status = 'PENDING'",
        (workspace_id,),
    ).fetchone()[0])
    return {
        "writer_task_count": task_total,
        "writer_tasks_ready": task_ready,
        "open_risks": open_risks,
        "pending_checklist_items": pending_checklist,
    }


def transition_workspace(
    workspace_id: str,
    *,
    target_stage: str,
    actor: str,
    note: str,
) -> dict[str, Any]:
    initialize_schema()
    workspace_id = _validate_identifier(workspace_id, "workspace_id")
    target_stage = _safe_text(target_stage).upper()
    actor = _safe_text(actor)
    note = _safe_text(note)
    if target_stage not in LIFECYCLE:
        raise ValueError(f"Invalid lifecycle stage: {target_stage}")
    if target_stage == "SUBMITTED":
        raise ValueError("V17 cannot submit applications; final submission requires a separate authorized submission action")
    if not actor:
        raise ValueError("actor is required")
    if not note:
        raise ValueError("review note is required")

    now = _utc_now()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM application_staging_v17 WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Workspace not found: {workspace_id}")
        current_stage = str(row["stage"])
        allowed = TRANSITIONS.get(current_stage, set())
        if target_stage not in allowed:
            raise ValueError(f"Invalid transition: {current_stage} -> {target_stage}")

        gates = _gate_state(connection, workspace_id)
        if target_stage == "READY_FOR_REVIEW":
            if gates["writer_task_count"] == 0:
                raise ValueError("No application questions are available for writer review")
            if gates["writer_tasks_ready"] != gates["writer_task_count"]:
                raise ValueError("Every writer task must have a reviewed draft before READY_FOR_REVIEW")
        if target_stage == "APPROVED":
            if current_stage != "READY_FOR_REVIEW":
                raise ValueError("Human approval is only allowed from READY_FOR_REVIEW")
        if target_stage == "READY_FOR_SUBMISSION":
            if not bool(row["human_approved"]):
                raise ValueError("Human approval is required before READY_FOR_SUBMISSION")
            if int(row["readiness_score"]) < 75:
                raise ValueError("Readiness score must be at least 75 before READY_FOR_SUBMISSION")
            if gates["open_risks"]:
                raise ValueError("All compliance risks must be resolved before READY_FOR_SUBMISSION")
            if gates["pending_checklist_items"]:
                raise ValueError("All checklist items must be VERIFIED or NOT_APPLICABLE before READY_FOR_SUBMISSION")

        human_approved = int(row["human_approved"])
        approved_by = str(row["approved_by"])
        approved_at = str(row["approved_at"])
        if target_stage == "APPROVED":
            human_approved = 1
            approved_by = actor
            approved_at = now
        elif target_stage == "DRAFTING":
            human_approved = 0
            approved_by = ""
            approved_at = ""

        connection.execute(
            """
            UPDATE application_staging_v17
            SET stage = ?, human_approved = ?, approved_by = ?, approved_at = ?, updated_at = ?
            WHERE workspace_id = ?
            """,
            (target_stage, human_approved, approved_by, approved_at, now, workspace_id),
        )
        connection.execute(
            """
            INSERT INTO application_review_events_v17 (
                event_id, workspace_id, event_type, from_stage, to_stage,
                actor, note, created_at
            ) VALUES (?, ?, 'STAGE_TRANSITION', ?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, workspace_id, current_stage, target_stage, actor, note, now),
        )
        connection.commit()

    _write_snapshot(workspace_id)
    return get_workspace(workspace_id)


def _write_snapshot(workspace_id: str) -> Path:
    payload = get_workspace(workspace_id)
    output_dir = _root() / "data" / "staging_v17" / workspace_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "workspace.json"
    temporary = output_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    return output_path


def health() -> dict[str, Any]:
    initialize_schema()
    with _connect() as connection:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    required = {
        "application_staging_v17",
        "application_drafts_v17",
        "application_risks_v17",
        "application_checklist_v17",
        "application_review_events_v17",
    }
    return {
        "healthy": required.issubset(tables),
        "version": 17,
        "database": str(_db_path()),
        "tables_ready": required.issubset(tables),
        "human_approval_required": True,
        "submission_enabled": False,
        "lifecycle": list(LIFECYCLE),
    }
