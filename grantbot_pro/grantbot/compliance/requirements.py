from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from grantbot.core.database import connection, utc_now
from grantbot.evidence.repository import list_requirements
from grantbot.master.database import initialize_master_schema
from grantbot.review.staging_v17 import (
    get_workspace,
    initialize_schema as initialize_staging_schema,
)


REVIEW_STATUSES = {"PENDING", "SATISFIED", "NOT_APPLICABLE"}
BLOCKING_LEVELS = {"MANDATORY", "CONDITIONAL"}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normal(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean(value).casefold())


def _stable_checklist_id(workspace_id: str, requirement_id: str) -> str:
    digest = hashlib.sha256(
        f"{workspace_id}\x1f{requirement_id}".encode("utf-8")
    ).hexdigest()[:24]
    return f"mreq_{digest}"


def initialize_requirement_schema() -> None:
    initialize_master_schema()
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS requirement_reviews_v20 (
                workspace_id TEXT NOT NULL,
                requirement_id TEXT NOT NULL,
                opportunity_id TEXT NOT NULL,
                category TEXT NOT NULL,
                requirement_level TEXT NOT NULL,
                requirement_text TEXT NOT NULL,
                document_id TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                section TEXT NOT NULL,
                authority_type TEXT NOT NULL,
                authority_rank INTEGER NOT NULL,
                source_url TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                evidence_note TEXT NOT NULL DEFAULT '',
                evidence_source TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT NOT NULL DEFAULT '',
                checklist_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, requirement_id)
            );

            CREATE INDEX IF NOT EXISTS idx_requirement_reviews_v20_gate
                ON requirement_reviews_v20(
                    workspace_id, requirement_level, status
                );

            CREATE TABLE IF NOT EXISTS requirement_review_events_v20 (
                event_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                requirement_id TEXT NOT NULL,
                from_status TEXT NOT NULL,
                to_status TEXT NOT NULL,
                actor TEXT NOT NULL,
                evidence_note TEXT NOT NULL,
                evidence_source TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_requirement_events_v20_workspace
                ON requirement_review_events_v20(
                    workspace_id, requirement_id, created_at
                );
            """
        )


def _effective_requirements(opportunity_id: str) -> list[dict[str, Any]]:
    raw = list_requirements(
        opportunity_id=opportunity_id,
        authoritative_only=True,
    )
    selected: dict[str, dict[str, Any]] = {}
    for item in raw:
        text_key = _normal(item.get("text"))
        if not text_key:
            continue
        current = selected.get(text_key)
        if current is None:
            selected[text_key] = item
            continue
        candidate_rank = int(item.get("authority_rank", 9))
        current_rank = int(current.get("authority_rank", 9))
        if candidate_rank < current_rank:
            selected[text_key] = item
        elif candidate_rank == current_rank and float(
            item.get("confidence", 0)
        ) > float(current.get("confidence", 0)):
            selected[text_key] = item
    return sorted(
        selected.values(),
        key=lambda item: (
            int(item.get("authority_rank", 9)),
            int(item.get("page_number", 0)),
            str(item.get("requirement_id", "")),
        ),
    )


def _mirror_checklist(
    *,
    workspace_id: str,
    requirement_id: str,
    level: str,
    text: str,
    status: str,
    actor: str,
    note: str,
) -> str:
    if level not in BLOCKING_LEVELS:
        return ""
    initialize_staging_schema()
    checklist_id = _stable_checklist_id(workspace_id, requirement_id)
    checklist_status = {
        "PENDING": "PENDING",
        "SATISFIED": "VERIFIED",
        "NOT_APPLICABLE": "NOT_APPLICABLE",
    }[status]
    now = utc_now()
    item_type = f"AUTHORITATIVE_{level}_REQUIREMENT"
    item_text = f"[{level}] {text}"
    with connection() as conn:
        workspace = conn.execute(
            "SELECT workspace_id FROM application_staging_v17 "
            "WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        if workspace is None:
            raise FileNotFoundError(f"Workspace not found: {workspace_id}")
        conn.execute(
            """
            INSERT INTO application_checklist_v17(
                checklist_id, workspace_id, item_type, item_text,
                status, note, updated_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(checklist_id) DO UPDATE SET
                item_type=excluded.item_type,
                item_text=excluded.item_text,
                status=excluded.status,
                note=excluded.note,
                updated_by=excluded.updated_by,
                updated_at=excluded.updated_at
            """,
            (
                checklist_id,
                workspace_id,
                item_type,
                item_text,
                checklist_status,
                note,
                actor,
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE application_staging_v17 SET updated_at=? "
            "WHERE workspace_id=?",
            (now, workspace_id),
        )
    return checklist_id


def sync_requirements(
    workspace_id: str,
    *,
    actor: str = "system",
) -> dict[str, Any]:
    initialize_requirement_schema()
    workspace = get_workspace(workspace_id)
    opportunity_id = _clean(workspace.get("opportunity_id"))
    if not opportunity_id:
        raise ValueError("Workspace has no opportunity_id")
    actor = _clean(actor) or "system"
    requirements = _effective_requirements(opportunity_id)
    now = utc_now()
    active_ids: set[str] = set()
    with connection() as conn:
        for item in requirements:
            requirement_id = _clean(item.get("requirement_id"))
            if not requirement_id:
                continue
            active_ids.add(requirement_id)
            level = (
                _clean(item.get("requirement_level")).upper()
                or "OPTIONAL"
            )
            if level not in {"MANDATORY", "CONDITIONAL", "OPTIONAL"}:
                level = "OPTIONAL"
            existing = conn.execute(
                "SELECT status,evidence_note,evidence_source,reviewed_by "
                "FROM requirement_reviews_v20 "
                "WHERE workspace_id=? AND requirement_id=?",
                (workspace_id, requirement_id),
            ).fetchone()
            status = "PENDING" if existing is None else str(existing["status"])
            note = "" if existing is None else str(existing["evidence_note"])
            source = "" if existing is None else str(existing["evidence_source"])
            reviewed_by = "" if existing is None else str(existing["reviewed_by"])
            checklist_id = (
                _stable_checklist_id(workspace_id, requirement_id)
                if level in BLOCKING_LEVELS
                else ""
            )
            conn.execute(
                """
                INSERT INTO requirement_reviews_v20(
                    workspace_id, requirement_id, opportunity_id, category,
                    requirement_level, requirement_text, document_id,
                    page_number, section, authority_type, authority_rank,
                    source_url, confidence, status, evidence_note,
                    evidence_source, reviewed_by, reviewed_at,
                    checklist_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)
                ON CONFLICT(workspace_id, requirement_id) DO UPDATE SET
                    opportunity_id=excluded.opportunity_id,
                    category=excluded.category,
                    requirement_level=excluded.requirement_level,
                    requirement_text=excluded.requirement_text,
                    document_id=excluded.document_id,
                    page_number=excluded.page_number,
                    section=excluded.section,
                    authority_type=excluded.authority_type,
                    authority_rank=excluded.authority_rank,
                    source_url=excluded.source_url,
                    confidence=excluded.confidence,
                    checklist_id=excluded.checklist_id,
                    updated_at=excluded.updated_at
                """,
                (
                    workspace_id,
                    requirement_id,
                    opportunity_id,
                    _clean(item.get("category")).upper() or "GENERAL",
                    level,
                    _clean(item.get("text")),
                    _clean(item.get("document_id")),
                    int(item.get("page_number", 0)),
                    _clean(item.get("section")),
                    _clean(item.get("authority_type")).upper(),
                    int(item.get("authority_rank", 9)),
                    _clean(item.get("source_url")),
                    float(item.get("confidence", 0)),
                    status,
                    note,
                    source,
                    reviewed_by,
                    checklist_id,
                    now,
                    now,
                ),
            )
    for item in requirement_rows(workspace_id, sync=False):
        if item["requirement_id"] not in active_ids:
            continue
        if item["requirement_level"] in BLOCKING_LEVELS:
            _mirror_checklist(
                workspace_id=workspace_id,
                requirement_id=item["requirement_id"],
                level=item["requirement_level"],
                text=item["requirement_text"],
                status=item["status"],
                actor=item["reviewed_by"] or actor,
                note=item["evidence_note"],
            )
    return requirement_summary(workspace_id, sync=False)


def requirement_rows(
    workspace_id: str,
    *,
    sync: bool = True,
) -> list[dict[str, Any]]:
    initialize_requirement_schema()
    if sync:
        sync_requirements(workspace_id)
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM requirement_reviews_v20
            WHERE workspace_id=?
            ORDER BY
                CASE requirement_level
                    WHEN 'MANDATORY' THEN 1
                    WHEN 'CONDITIONAL' THEN 2
                    ELSE 3
                END,
                authority_rank,
                page_number,
                requirement_id
            """,
            (workspace_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def set_requirement_status(
    workspace_id: str,
    requirement_id: str,
    *,
    status: str,
    actor: str,
    evidence_note: str,
    evidence_source: str,
    allow_not_applicable: bool = False,
) -> dict[str, Any]:
    initialize_requirement_schema()
    sync_requirements(workspace_id, actor=actor)
    status = _clean(status).upper()
    actor = _clean(actor)
    evidence_note = _clean(evidence_note)
    evidence_source = _clean(evidence_source)
    if status not in REVIEW_STATUSES - {"PENDING"}:
        raise ValueError("status must be SATISFIED or NOT_APPLICABLE")
    if not actor:
        raise ValueError("actor is required")
    if not evidence_note or not evidence_source:
        raise ValueError(
            "evidence_note and evidence_source are required "
            "for requirement review"
        )
    now = utc_now()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM requirement_reviews_v20 "
            "WHERE workspace_id=? AND requirement_id=?",
            (workspace_id, requirement_id),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(
                f"Requirement not found: {requirement_id}"
            )
        level = str(row["requirement_level"])
        if status == "NOT_APPLICABLE":
            if level == "MANDATORY":
                raise ValueError(
                    "Mandatory requirements cannot be marked NOT_APPLICABLE"
                )
            if not allow_not_applicable:
                raise PermissionError(
                    "NOT_APPLICABLE requires an authorized requirement reviewer"
                )
        previous = str(row["status"])
        conn.execute(
            """
            UPDATE requirement_reviews_v20
            SET status=?, evidence_note=?, evidence_source=?,
                reviewed_by=?, reviewed_at=?, updated_at=?
            WHERE workspace_id=? AND requirement_id=?
            """,
            (
                status,
                evidence_note,
                evidence_source,
                actor,
                now,
                now,
                workspace_id,
                requirement_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO requirement_review_events_v20(
                event_id, workspace_id, requirement_id, from_status,
                to_status, actor, evidence_note, evidence_source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                workspace_id,
                requirement_id,
                previous,
                status,
                actor,
                evidence_note,
                evidence_source,
                now,
            ),
        )
    refreshed = next(
        item
        for item in requirement_rows(workspace_id, sync=False)
        if item["requirement_id"] == requirement_id
    )
    if refreshed["requirement_level"] in BLOCKING_LEVELS:
        _mirror_checklist(
            workspace_id=workspace_id,
            requirement_id=requirement_id,
            level=refreshed["requirement_level"],
            text=refreshed["requirement_text"],
            status=refreshed["status"],
            actor=actor,
            note=f"{evidence_note} | Evidence: {evidence_source}",
        )
    return refreshed


def requirement_summary(
    workspace_id: str,
    *,
    sync: bool = True,
) -> dict[str, Any]:
    rows = requirement_rows(workspace_id, sync=sync)
    blockers: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {
        "MANDATORY": {
            "total": 0,
            "pending": 0,
            "satisfied": 0,
            "not_applicable": 0,
        },
        "CONDITIONAL": {
            "total": 0,
            "pending": 0,
            "satisfied": 0,
            "not_applicable": 0,
        },
        "OPTIONAL": {
            "total": 0,
            "pending": 0,
            "satisfied": 0,
            "not_applicable": 0,
        },
    }
    for item in rows:
        level = str(item["requirement_level"])
        status = str(item["status"])
        bucket = counts.setdefault(
            level,
            {
                "total": 0,
                "pending": 0,
                "satisfied": 0,
                "not_applicable": 0,
            },
        )
        bucket["total"] += 1
        bucket[status.casefold()] += 1
        if level == "MANDATORY" and status != "SATISFIED":
            blockers.append(item)
        elif level == "CONDITIONAL" and status == "PENDING":
            blockers.append(item)
    return {
        "workspace_id": workspace_id,
        "requirement_count": len(rows),
        "counts": counts,
        "blocking_count": len(blockers),
        "blockers": blockers,
        "ready": not blockers,
        "submission_enabled": False,
    }
