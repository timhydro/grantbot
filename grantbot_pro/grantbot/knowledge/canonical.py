from __future__ import annotations

import json
import uuid
from typing import Any

from grantbot.core.database import connection, utc_now
from grantbot.master.database import initialize_master_schema


FACT_TYPES = {
    "VERIFIED_FACT",
    "USER_PROVIDED_FACT",
    "CALCULATED_VALUE",
    "EXTERNAL_SOURCE",
    "REASONABLE_PROJECTION",
    "UNVERIFIED_CLAIM",
    "MISSING_INFORMATION",
}

VERIFICATION_STATES = {
    "VERIFIED",
    "APPROVED",
    "UNVERIFIED",
    "MISSING",
    "SUPERSEDED",
    "EXPIRED",
}

ACTIVE_VERIFICATION_STATES = {
    "VERIFIED",
    "APPROVED",
    "UNVERIFIED",
    "MISSING",
}


def _validate(value: str, allowed: set[str], label: str) -> str:
    clean = value.strip().upper()
    if clean not in allowed:
        raise ValueError(f"Invalid {label}: {clean}")
    return clean


def set_fact(
    *,
    category: str,
    fact_key: str,
    value: Any,
    fact_type: str,
    verification_state: str,
    source: str,
    source_type: str = "",
    confidence: float = 1.0,
    notes: str = "",
    actor: str = "system",
) -> dict[str, Any]:
    initialize_master_schema()
    category = category.strip().lower()
    fact_key = fact_key.strip().lower()
    if not category or not fact_key:
        raise ValueError("category and fact_key are required")
    fact_type = _validate(fact_type, FACT_TYPES, "fact_type")
    verification_state = _validate(
        verification_state,
        ACTIVE_VERIFICATION_STATES,
        "verification_state",
    )
    if not 0 <= float(confidence) <= 1:
        raise ValueError("confidence must be between 0 and 1")
    if verification_state in {"VERIFIED", "APPROVED"} and not source.strip():
        raise ValueError("Verified or approved facts require a source")

    now = utc_now()
    fact_id = uuid.uuid4().hex
    serialized = json.dumps(value, ensure_ascii=False)
    with connection() as conn:
        previous = conn.execute(
            """
            SELECT fact_id
            FROM canonical_facts
            WHERE fact_key=? AND valid_to=''
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (fact_key,),
        ).fetchone()
        supersedes = str(previous["fact_id"]) if previous else ""
        if previous:
            conn.execute(
                """
                UPDATE canonical_facts
                SET valid_to=?, verification_state='SUPERSEDED', updated_at=?
                WHERE fact_id=?
                """,
                (now, now, supersedes),
            )
        conn.execute(
            """
            INSERT INTO canonical_facts(
                fact_id, category, fact_key, value_json, fact_type,
                verification_state, source, source_type, confidence,
                notes, actor, supersedes_fact_id, valid_from, valid_to,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
            """,
            (
                fact_id,
                category,
                fact_key,
                serialized,
                fact_type,
                verification_state,
                source.strip(),
                source_type.strip(),
                float(confidence),
                notes.strip(),
                actor.strip() or "system",
                supersedes,
                now,
                now,
                now,
            ),
        )
    return get_fact(fact_id)


def get_fact(fact_id: str) -> dict[str, Any]:
    initialize_master_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM canonical_facts WHERE fact_id=?",
            (fact_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Canonical fact not found: {fact_id}")
    item = dict(row)
    try:
        item["value"] = json.loads(str(item.pop("value_json")))
    except json.JSONDecodeError:
        item["value"] = None
    return item


def current_facts(
    *,
    category: str | None = None,
    verification_states: list[str] | None = None,
) -> list[dict[str, Any]]:
    initialize_master_schema()
    sql = "SELECT * FROM canonical_facts WHERE valid_to=''"
    params: list[Any] = []
    if category:
        sql += " AND category=?"
        params.append(category.strip().lower())
    if verification_states:
        states = [
            _validate(item, VERIFICATION_STATES, "verification_state")
            for item in verification_states
        ]
        marks = ",".join("?" for _ in states)
        sql += f" AND verification_state IN ({marks})"
        params.extend(states)
    sql += " ORDER BY category, fact_key"
    with connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        try:
            item["value"] = json.loads(str(item.pop("value_json")))
        except json.JSONDecodeError:
            item["value"] = None
        output.append(item)
    return output


def migrate_legacy_facts() -> dict[str, int]:
    initialize_master_schema()
    with connection() as conn:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='facts'"
        ).fetchone()
        if table is None:
            return {"migrated": 0, "skipped": 0}
        legacy = conn.execute(
            """
            SELECT id, category, fact_key, value, status, source, confidence, notes
            FROM facts
            ORDER BY id
            """
        ).fetchall()
        source_rows = conn.execute(
            "SELECT source FROM canonical_facts WHERE source LIKE 'legacy_fact:%'"
        ).fetchall()
    existing_sources = {str(row["source"]) for row in source_rows}
    migrated = 0
    skipped = 0
    for row in legacy:
        legacy_source = f"legacy_fact:{row['id']}"
        if legacy_source in existing_sources:
            skipped += 1
            continue
        status = str(row["status"]).upper()
        if status == "APPROVED":
            fact_type = "USER_PROVIDED_FACT"
            state = "APPROVED"
        elif status == "VERIFIED":
            fact_type = "VERIFIED_FACT"
            state = "VERIFIED"
        elif status == "DRAFT":
            fact_type = "REASONABLE_PROJECTION"
            state = "UNVERIFIED"
        else:
            fact_type = "MISSING_INFORMATION"
            state = "MISSING"
        set_fact(
            category=str(row["category"]),
            fact_key=str(row["fact_key"]),
            value=row["value"],
            fact_type=fact_type,
            verification_state=state,
            source=legacy_source,
            source_type=str(row["source"] or "legacy"),
            confidence=float(row["confidence"] or 0),
            notes=str(row["notes"] or ""),
            actor="legacy-migration",
        )
        migrated += 1
    return {"migrated": migrated, "skipped": skipped}


def conflicts() -> list[dict[str, Any]]:
    initialize_master_schema()
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT fact_key, COUNT(*) AS versions
            FROM canonical_facts
            GROUP BY fact_key
            HAVING SUM(CASE WHEN valid_to='' THEN 1 ELSE 0 END) > 1
            """
        ).fetchall()
    return [dict(row) for row in rows]
