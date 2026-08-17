from __future__ import annotations

import json
import uuid
from typing import Any

from grantbot.core.database import connection, utc_now


MASTER_SCHEMA_VERSION = 1


def initialize_master_schema() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS master_schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS draft_revisions_v18 (
                revision_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                facts_json TEXT NOT NULL,
                quality_json TEXT NOT NULL,
                claims_json TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(workspace_id, task_id, version)
            );

            CREATE INDEX IF NOT EXISTS idx_draft_revisions_v18_workspace
                ON draft_revisions_v18(workspace_id, task_id, version);

            CREATE TABLE IF NOT EXISTS writer_feedback_v18 (
                feedback_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                revision_id TEXT,
                before_text TEXT NOT NULL,
                after_text TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                edit_tags_json TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                reviewer_score REAL,
                outcome TEXT NOT NULL,
                award_amount REAL,
                section_type TEXT NOT NULL,
                funder_archetype TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_writer_feedback_v18_context
                ON writer_feedback_v18(section_type, funder_archetype, accepted);

            CREATE TABLE IF NOT EXISTS application_packets_v19 (
                packet_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                status TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                archive_path TEXT NOT NULL,
                human_approved INTEGER NOT NULL DEFAULT 0,
                approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT NOT NULL DEFAULT '',
                sealed_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, revision)
            );

            CREATE INDEX IF NOT EXISTS idx_application_packets_v19_workspace
                ON application_packets_v19(workspace_id, revision);

            CREATE TABLE IF NOT EXISTS packet_attachments_v19 (
                attachment_id TEXT PRIMARY KEY,
                packet_id TEXT NOT NULL,
                logical_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                required INTEGER NOT NULL DEFAULT 1,
                verified INTEGER NOT NULL DEFAULT 0,
                verified_by TEXT NOT NULL DEFAULT '',
                verified_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(packet_id)
                    REFERENCES application_packets_v19(packet_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS packet_events_v19 (
                event_id TEXT PRIMARY KEY,
                packet_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(packet_id)
                    REFERENCES application_packets_v19(packet_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS master_approvals (
                approval_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                approval_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO master_schema_meta(key, value, updated_at)
            VALUES ('schema_version', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (str(MASTER_SCHEMA_VERSION), utc_now()),
        )


def next_revision_version(workspace_id: str, task_id: str) -> int:
    initialize_master_schema()
    with connection() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS current_version
            FROM draft_revisions_v18
            WHERE workspace_id=? AND task_id=?
            """,
            (workspace_id, task_id),
        ).fetchone()
    return int(row["current_version"]) + 1


def save_revision(
    *,
    workspace_id: str,
    task_id: str,
    content: str,
    status: str,
    facts: list[dict[str, Any]],
    quality: dict[str, Any],
    claims: dict[str, Any],
    provider: str,
    model: str,
) -> dict[str, Any]:
    initialize_master_schema()
    version = next_revision_version(workspace_id, task_id)
    revision_id = uuid.uuid4().hex
    created_at = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO draft_revisions_v18(
                revision_id, workspace_id, task_id, version, content, status,
                facts_json, quality_json, claims_json, provider, model, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                workspace_id,
                task_id,
                version,
                content,
                status,
                json.dumps(facts, ensure_ascii=False),
                json.dumps(quality, ensure_ascii=False),
                json.dumps(claims, ensure_ascii=False),
                provider,
                model,
                created_at,
            ),
        )
    return {
        "revision_id": revision_id,
        "workspace_id": workspace_id,
        "task_id": task_id,
        "version": version,
        "status": status,
        "created_at": created_at,
    }


def list_revisions(workspace_id: str, task_id: str | None = None) -> list[dict[str, Any]]:
    initialize_master_schema()
    sql = """
        SELECT *
        FROM draft_revisions_v18
        WHERE workspace_id=?
    """
    params: list[Any] = [workspace_id]
    if task_id:
        sql += " AND task_id=?"
        params.append(task_id)
    sql += " ORDER BY task_id, version"
    with connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("facts_json", "quality_json", "claims_json"):
            try:
                item[key[:-5]] = json.loads(str(item.pop(key)))
            except json.JSONDecodeError:
                item[key[:-5]] = {} if key != "facts_json" else []
        output.append(item)
    return output


def record_feedback(
    *,
    workspace_id: str,
    task_id: str,
    revision_id: str | None,
    before_text: str,
    after_text: str,
    accepted: bool,
    edit_tags: list[str],
    reviewer: str,
    reviewer_score: float | None,
    outcome: str,
    award_amount: float | None,
    section_type: str,
    funder_archetype: str,
) -> dict[str, Any]:
    initialize_master_schema()
    feedback_id = uuid.uuid4().hex
    created_at = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO writer_feedback_v18(
                feedback_id, workspace_id, task_id, revision_id,
                before_text, after_text, accepted, edit_tags_json,
                reviewer, reviewer_score, outcome, award_amount,
                section_type, funder_archetype, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_id,
                workspace_id,
                task_id,
                revision_id,
                before_text,
                after_text,
                int(accepted),
                json.dumps(sorted(set(edit_tags)), ensure_ascii=False),
                reviewer,
                reviewer_score,
                outcome,
                award_amount,
                section_type,
                funder_archetype,
                created_at,
            ),
        )
    return {
        "feedback_id": feedback_id,
        "workspace_id": workspace_id,
        "task_id": task_id,
        "accepted": accepted,
        "created_at": created_at,
    }


def feedback_rows() -> list[dict[str, Any]]:
    initialize_master_schema()
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM writer_feedback_v18 ORDER BY created_at DESC"
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        try:
            item["edit_tags"] = json.loads(str(item.pop("edit_tags_json")))
        except json.JSONDecodeError:
            item["edit_tags"] = []
        item["accepted"] = bool(item["accepted"])
        output.append(item)
    return output
