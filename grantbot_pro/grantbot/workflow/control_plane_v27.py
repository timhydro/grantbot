from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from grantbot.agents.pipeline_v26 import build_execution_plan
from grantbot.review.staging_v17 import (
    create_workspace,
    get_workspace,
    list_workspaces,
    transition_workspace,
)


RUN_STATES = {
    "CREATED",
    "ACTIVE",
    "WAITING_FOR_USER",
    "WAITING_FOR_HUMAN_REVIEW",
    "READY_FOR_SUBMISSION",
    "COMPLETED",
    "FAILED",
}


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    run_id: str
    workspace_id: str
    opportunity_id: str
    state: str
    current_stage: str
    last_error: str
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
            CREATE TABLE IF NOT EXISTS workflow_runs_v27 (
                run_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL UNIQUE,
                opportunity_id TEXT NOT NULL,
                state TEXT NOT NULL,
                current_stage TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workflow_events_v27 (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES workflow_runs_v27(run_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_workflow_runs_state_v27
                ON workflow_runs_v27(state, updated_at);
            CREATE INDEX IF NOT EXISTS idx_workflow_events_run_v27
                ON workflow_events_v27(run_id, created_at);
            """
        )
        connection.commit()


def _row_to_run(row: sqlite3.Row) -> WorkflowRun:
    return WorkflowRun(
        run_id=str(row["run_id"]),
        workspace_id=str(row["workspace_id"]),
        opportunity_id=str(row["opportunity_id"]),
        state=str(row["state"]),
        current_stage=str(row["current_stage"]),
        last_error=str(row["last_error"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _record_event(connection: sqlite3.Connection, run_id: str, event_type: str, actor: str, payload: dict[str, Any]) -> None:
    connection.execute(
        "INSERT INTO workflow_events_v27 (event_id, run_id, event_type, actor, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, run_id, event_type, actor, json.dumps(payload, ensure_ascii=False), _utc_now()),
    )


def _derive_state(workspace: dict[str, Any]) -> str:
    stage = str(workspace.get("stage") or "")
    if stage == "READY_FOR_SUBMISSION":
        return "READY_FOR_SUBMISSION"
    if stage in {"READY_FOR_REVIEW", "APPROVED"}:
        return "WAITING_FOR_HUMAN_REVIEW"
    if stage == "SUBMITTED":
        return "COMPLETED"

    open_risks = sum(1 for item in workspace.get("risks", []) if item.get("status") == "OPEN")
    pending = sum(1 for item in workspace.get("checklist", []) if item.get("status") == "PENDING")
    if open_risks or pending:
        return "WAITING_FOR_USER"
    return "ACTIVE"


def start_run(opportunity_id: str, *, manual_urls: list[str] | None = None, refresh_analysis: bool = False, actor: str = "system") -> dict[str, Any]:
    initialize_schema()
    workspace = create_workspace(
        opportunity_id,
        manual_urls=manual_urls or [],
        refresh_analysis=refresh_analysis,
    )
    workspace_id = str(workspace["workspace_id"])
    now = _utc_now()

    with _connect() as connection:
        existing = connection.execute(
            "SELECT * FROM workflow_runs_v27 WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if existing is None:
            run_id = uuid.uuid4().hex
            state = _derive_state(workspace)
            connection.execute(
                "INSERT INTO workflow_runs_v27 (run_id, workspace_id, opportunity_id, state, current_stage, last_error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, '', ?, ?)",
                (run_id, workspace_id, opportunity_id, state, str(workspace["stage"]), now, now),
            )
            _record_event(connection, run_id, "RUN_CREATED", actor, {"workspace_id": workspace_id, "stage": workspace["stage"]})
        else:
            run_id = str(existing["run_id"])
            state = _derive_state(workspace)
            connection.execute(
                "UPDATE workflow_runs_v27 SET state = ?, current_stage = ?, last_error = '', updated_at = ? WHERE run_id = ?",
                (state, str(workspace["stage"]), now, run_id),
            )
            _record_event(connection, run_id, "RUN_RESUMED", actor, {"stage": workspace["stage"]})
        connection.commit()

    return get_run(run_id)


def get_run(run_id: str) -> dict[str, Any]:
    initialize_schema()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM workflow_runs_v27 WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise FileNotFoundError(f"Workflow run not found: {run_id}")
        events = connection.execute(
            "SELECT event_id, event_type, actor, payload_json, created_at FROM workflow_events_v27 WHERE run_id = ? ORDER BY created_at, event_id",
            (run_id,),
        ).fetchall()
    run = _row_to_run(row)
    workspace = get_workspace(run.workspace_id)
    return {
        **run.to_dict(),
        "workspace": workspace,
        "events": [
            {
                "event_id": str(item["event_id"]),
                "event_type": str(item["event_type"]),
                "actor": str(item["actor"]),
                "payload": json.loads(str(item["payload_json"])),
                "created_at": str(item["created_at"]),
            }
            for item in events
        ],
        "safe_to_submit": False,
    }


def list_runs() -> list[dict[str, Any]]:
    initialize_schema()
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM workflow_runs_v27 ORDER BY updated_at DESC").fetchall()
    return [_row_to_run(row).to_dict() for row in rows]


def advance_run(run_id: str, *, target_stage: str, actor: str, note: str) -> dict[str, Any]:
    current = get_run(run_id)
    workspace = transition_workspace(
        current["workspace_id"],
        target_stage=target_stage,
        actor=actor,
        note=note,
    )
    state = _derive_state(workspace)
    now = _utc_now()
    with _connect() as connection:
        connection.execute(
            "UPDATE workflow_runs_v27 SET state = ?, current_stage = ?, last_error = '', updated_at = ? WHERE run_id = ?",
            (state, str(workspace["stage"]), now, run_id),
        )
        _record_event(connection, run_id, "RUN_ADVANCED", actor, {"target_stage": target_stage, "note": note})
        connection.commit()
    return get_run(run_id)


def synchronize_run(run_id: str, *, actor: str = "system") -> dict[str, Any]:
    current = get_run(run_id)
    workspace = current["workspace"]
    state = _derive_state(workspace)
    with _connect() as connection:
        connection.execute(
            "UPDATE workflow_runs_v27 SET state = ?, current_stage = ?, updated_at = ? WHERE run_id = ?",
            (state, str(workspace["stage"]), _utc_now(), run_id),
        )
        _record_event(connection, run_id, "RUN_SYNCHRONIZED", actor, {"state": state, "stage": workspace["stage"]})
        connection.commit()
    return get_run(run_id)


def execution_snapshot(run_id: str) -> dict[str, Any]:
    current = get_run(run_id)
    workspace = current["workspace"]
    analysis = workspace.get("analysis") or {}
    blueprint = analysis.get("blueprint") or {}
    opportunity = {
        "title": workspace.get("title", ""),
        "funder": workspace.get("funder", ""),
        "description": blueprint.get("description", ""),
        "eligibility": " ".join(blueprint.get("eligibility", []) if isinstance(blueprint.get("eligibility"), list) else [str(blueprint.get("eligibility") or "")]),
        "source_url": blueprint.get("source_url", "") or blueprint.get("url", ""),
    }
    facts = []
    for task in workspace.get("writer_tasks", []):
        if task.get("response"):
            facts.append({
                "key": f"draft_{task.get('task_id')}",
                "value": task.get("response"),
                "status": "DRAFT",
                "source": "application_staging_v17",
            })
    plan = build_execution_plan(opportunity=opportunity, facts=facts)
    return {
        "run": {key: current[key] for key in ("run_id", "workspace_id", "opportunity_id", "state", "current_stage")},
        "execution_plan": plan.to_dict(),
        "safe_to_submit": False,
    }


def health() -> dict[str, Any]:
    initialize_schema()
    return {
        "healthy": True,
        "version": 27,
        "persistent": True,
        "resumable": True,
        "human_approval_required": True,
        "submission_enabled": False,
        "run_states": sorted(RUN_STATES),
        "workspace_count": len(list_workspaces()),
        "run_count": len(list_runs()),
    }
