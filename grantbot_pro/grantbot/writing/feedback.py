from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any
import uuid


def _ensure_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS writer_feedback (
            feedback_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            workspace_id TEXT,
            task_id TEXT,
            opportunity_id TEXT,
            provider TEXT,
            model TEXT,
            prompt TEXT,
            draft TEXT,
            facts_used_json TEXT,
            reviewer_action TEXT,
            reviewer_notes TEXT,
            quality_json TEXT,
            token_usage_json TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def record_writer_feedback(
    db_path: str,
    workspace_id: str | None,
    task_id: str | None,
    opportunity_id: str | None,
    provider: str,
    model: str,
    prompt: str,
    draft: str,
    facts_used: list[dict[str, Any]] | None,
    reviewer_action: str,
    reviewer_notes: str | None,
    quality: dict[str, Any] | None = None,
    token_usage: dict[str, Any] | None = None,
) -> str:
    _ensure_db(db_path)
    fid = uuid.uuid4().hex
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO writer_feedback (feedback_id, created_at, workspace_id, task_id, opportunity_id, provider, model, prompt, draft, facts_used_json, reviewer_action, reviewer_notes, quality_json, token_usage_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            fid,
            now,
            workspace_id,
            task_id,
            opportunity_id,
            provider,
            model,
            prompt,
            draft,
            json.dumps(facts_used or [], ensure_ascii=False),
            reviewer_action,
            reviewer_notes or "",
            json.dumps(quality or {}, ensure_ascii=False),
            json.dumps(token_usage or {}, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    return fid


def list_feedback(db_path: str, limit: int = 100) -> list[dict[str, Any]]:
    _ensure_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT feedback_id, created_at, workspace_id, task_id, opportunity_id, provider, model, draft, reviewer_action FROM writer_feedback ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(feedback_id=row[0], created_at=row[1], workspace_id=row[2], task_id=row[3], opportunity_id=row[4], provider=row[5], model=row[6], draft=row[7], reviewer_action=row[8]) for row in rows]
