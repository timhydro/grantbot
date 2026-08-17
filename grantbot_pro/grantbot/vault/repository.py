from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from grantbot.core.database import connection, utc_now
from grantbot.vault.files import resolve_object, validate_content, write_object
from grantbot.vault.schema import (
    CATEGORIES,
    REQUIREMENT_SCOPES,
    VERIFICATION_STATES,
    initialize_vault_schema,
)


def clean(value: Any, *, max_length: int = 10000) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > max_length:
        raise ValueError(f"Text exceeds maximum length of {max_length}")
    return text


def normalize_key(value: Any, label: str) -> str:
    text = clean(value, max_length=120).lower()
    text = re.sub(r"[^a-z0-9._:-]+", "_", text).strip("_.:-")
    if not text or len(text) > 120 or ".." in text:
        raise ValueError(f"Invalid {label}")
    return text


def identifier(value: Any, label: str) -> str:
    text = clean(value, max_length=120)
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", text) or ".." in text:
        raise ValueError(f"Invalid {label}")
    return text


def iso_date(value: Any, label: str, *, allow_blank: bool = True) -> str:
    text = clean(value, max_length=32)
    if allow_blank and not text:
        return ""
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD") from exc
    return parsed.isoformat()


def as_of_date(value: str | None = None) -> date:
    if value is None or not str(value).strip():
        return datetime.now(timezone.utc).date()
    return date.fromisoformat(iso_date(value, "as_of", allow_blank=False))


def _decode_document(row: Any) -> dict[str, Any]:
    item = dict(row)
    try:
        item["tags"] = json.loads(str(item.pop("tags_json")))
    except json.JSONDecodeError:
        item["tags"] = []
    item["is_current"] = bool(item.get("is_current"))
    item.pop("object_relative_path", None)
    return item


def _event(
    conn: Any,
    *,
    document_id: str,
    document_key: str,
    event_type: str,
    actor: str,
    detail: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO vault_events_v22(
            event_id, document_id, document_key, event_type,
            actor, detail_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            document_id,
            document_key,
            event_type,
            actor,
            json.dumps(detail, ensure_ascii=False, sort_keys=True),
            utc_now(),
        ),
    )


def store_document(
    *,
    document_key: str,
    title: str,
    category: str,
    filename: str,
    content: bytes,
    source_reference: str,
    actor: str,
    effective_date: str = "",
    expires_at: str = "",
    review_due_date: str = "",
    description: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    initialize_vault_schema()
    document_key = normalize_key(document_key, "document_key")
    title = clean(title, max_length=500)
    category = clean(category, max_length=80).upper()
    source_reference = clean(source_reference, max_length=2000)
    actor = clean(actor, max_length=500)
    description = clean(description, max_length=5000)
    effective = iso_date(effective_date, "effective_date")
    expires = iso_date(expires_at, "expires_at")
    review_due = iso_date(review_due_date, "review_due_date")
    if category not in CATEGORIES:
        raise ValueError(f"Invalid category: {category}")
    if not title or not source_reference or not actor:
        raise ValueError("title, source_reference, and actor are required")
    if effective and expires and date.fromisoformat(expires) < date.fromisoformat(effective):
        raise ValueError("expires_at cannot be before effective_date")
    safe_name, media_type, sha256 = validate_content(content, filename)
    object_relative_path = write_object(content, sha256)
    normalized_tags: list[str] = []
    for tag in tags or []:
        value = clean(tag, max_length=100).lower()
        if value and value not in normalized_tags:
            normalized_tags.append(value)
        if len(normalized_tags) >= 50:
            break

    with connection() as conn:
        identical = conn.execute(
            """
            SELECT * FROM vault_documents_v22
            WHERE document_key=? AND sha256=?
            ORDER BY version DESC LIMIT 1
            """,
            (document_key, sha256),
        ).fetchone()
        if identical is not None:
            return _decode_document(identical)
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS version "
            "FROM vault_documents_v22 WHERE document_key=?",
            (document_key,),
        ).fetchone()
        version = int(row["version"]) + 1
        current = conn.execute(
            "SELECT document_id FROM vault_documents_v22 "
            "WHERE document_key=? AND is_current=1",
            (document_key,),
        ).fetchone()
        document_id = f"vdoc_{uuid.uuid4().hex}"
        now = utc_now()
        conn.execute(
            """
            INSERT INTO vault_documents_v22(
                document_id, document_key, version, title, category,
                original_filename, media_type, byte_size, sha256,
                object_relative_path, verification_state, lifecycle_state,
                is_current, source_reference, effective_date, expires_at,
                review_due_date, description, tags_json,
                supersedes_document_id, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'UNVERIFIED',
                      'CANDIDATE', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                document_key,
                version,
                title,
                category,
                safe_name,
                media_type,
                len(content),
                sha256,
                object_relative_path,
                source_reference,
                effective,
                expires,
                review_due,
                description,
                json.dumps(normalized_tags, ensure_ascii=False),
                str(current["document_id"]) if current is not None else "",
                actor,
                now,
            ),
        )
        _event(
            conn,
            document_id=document_id,
            document_key=document_key,
            event_type="DOCUMENT_STORED",
            actor=actor,
            detail={
                "version": version,
                "sha256": sha256,
                "byte_size": len(content),
                "media_type": media_type,
                "candidate_only": True,
            },
        )
    return get_document(document_id)


def raw_document(document_id: str) -> dict[str, Any]:
    initialize_vault_schema()
    document_id = identifier(document_id, "document_id")
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM vault_documents_v22 WHERE document_id=?",
            (document_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Vault document not found: {document_id}")
    return dict(row)


def get_document(document_id: str) -> dict[str, Any]:
    return _decode_document(raw_document(document_id))


def resolve_document_path(document_id: str) -> Path:
    item = raw_document(document_id)
    try:
        return resolve_object(
            str(item["object_relative_path"]),
            str(item["sha256"]),
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Vault object missing for document: {document_id}"
        ) from exc


def document_freshness(
    document: dict[str, Any] | str,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    item = get_document(document) if isinstance(document, str) else dict(document)
    current = as_of_date(as_of)
    lifecycle = clean(item.get("lifecycle_state")).upper()
    verification = clean(item.get("verification_state")).upper()
    is_current = bool(item.get("is_current"))
    expires = clean(item.get("expires_at"))
    review_due = clean(item.get("review_due_date"))
    effective = clean(item.get("effective_date"))
    state = "CURRENT"
    if lifecycle == "REJECTED" or verification == "REJECTED":
        state = "REJECTED"
    elif lifecycle == "SUPERSEDED":
        state = "SUPERSEDED"
    elif lifecycle == "CANDIDATE" or not is_current:
        state = "CANDIDATE"
    elif expires and date.fromisoformat(expires) < current:
        state = "EXPIRED"
    elif review_due and date.fromisoformat(review_due) < current:
        state = "REVIEW_DUE"
    elif effective and date.fromisoformat(effective) > current:
        state = "NOT_YET_EFFECTIVE"
    elif verification not in {"VERIFIED", "APPROVED"}:
        state = "UNVERIFIED"
    return {
        "document_id": item.get("document_id"),
        "document_key": item.get("document_key"),
        "version": item.get("version"),
        "state": state,
        "verification_state": verification,
        "lifecycle_state": lifecycle,
        "is_current": is_current,
        "as_of": current.isoformat(),
        "expires_at": expires,
        "review_due_date": review_due,
        "days_to_expiry": (
            (date.fromisoformat(expires) - current).days if expires else None
        ),
        "days_to_review": (
            (date.fromisoformat(review_due) - current).days if review_due else None
        ),
        "usable_for_packet": state == "CURRENT" and verification == "APPROVED",
    }


def list_documents(
    *,
    category: str | None = None,
    current_only: bool = False,
    document_key: str | None = None,
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    initialize_vault_schema()
    sql = "SELECT * FROM vault_documents_v22 WHERE 1=1"
    params: list[Any] = []
    if category:
        normalized = clean(category, max_length=80).upper()
        if normalized not in CATEGORIES:
            raise ValueError(f"Invalid category: {normalized}")
        sql += " AND category=?"
        params.append(normalized)
    if current_only:
        sql += " AND is_current=1"
    if document_key:
        sql += " AND document_key=?"
        params.append(normalize_key(document_key, "document_key"))
    sql += " ORDER BY document_key, version DESC"
    with connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        item = _decode_document(row)
        item["freshness"] = document_freshness(item, as_of=as_of)
        output.append(item)
    return output


def review_document(
    document_id: str,
    *,
    verification_state: str,
    actor: str,
    review_note: str,
    review_due_date: str = "",
) -> dict[str, Any]:
    initialize_vault_schema()
    document_id = identifier(document_id, "document_id")
    verification_state = clean(verification_state, max_length=30).upper()
    actor = clean(actor, max_length=500)
    review_note = clean(review_note, max_length=5000)
    review_due = iso_date(review_due_date, "review_due_date")
    if verification_state not in VERIFICATION_STATES - {"UNVERIFIED"}:
        raise ValueError("verification_state must be VERIFIED, APPROVED, or REJECTED")
    if not actor or not review_note:
        raise ValueError("actor and review_note are required")
    resolve_document_path(document_id)
    now = utc_now()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM vault_documents_v22 WHERE document_id=?",
            (document_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Vault document not found: {document_id}")
        if str(row["lifecycle_state"]) == "SUPERSEDED":
            raise ValueError("Superseded vault document versions cannot be re-reviewed")
        lifecycle = "REJECTED" if verification_state == "REJECTED" else str(row["lifecycle_state"])
        conn.execute(
            """
            UPDATE vault_documents_v22
            SET verification_state=?, lifecycle_state=?, review_due_date=?,
                reviewed_by=?, reviewed_at=?, review_note=?
            WHERE document_id=?
            """,
            (
                verification_state,
                lifecycle,
                review_due,
                actor,
                now,
                review_note,
                document_id,
            ),
        )
        _event(
            conn,
            document_id=document_id,
            document_key=str(row["document_key"]),
            event_type="DOCUMENT_REVIEWED",
            actor=actor,
            detail={
                "verification_state": verification_state,
                "review_due_date": review_due,
                "review_note": review_note,
            },
        )
    return get_document(document_id)


def approve_document(
    document_id: str,
    *,
    actor: str,
    review_note: str,
    review_due_date: str = "",
) -> dict[str, Any]:
    reviewed = review_document(
        document_id,
        verification_state="APPROVED",
        actor=actor,
        review_note=review_note,
        review_due_date=review_due_date,
    )
    document_key = str(reviewed["document_key"])
    now = utc_now()
    with connection() as conn:
        prior = conn.execute(
            "SELECT * FROM vault_documents_v22 "
            "WHERE document_key=? AND is_current=1 AND document_id<>?",
            (document_key, document_id),
        ).fetchone()
        if prior is not None:
            conn.execute(
                """
                UPDATE vault_documents_v22
                SET is_current=0, lifecycle_state='SUPERSEDED'
                WHERE document_id=?
                """,
                (str(prior["document_id"]),),
            )
            _event(
                conn,
                document_id=str(prior["document_id"]),
                document_key=document_key,
                event_type="DOCUMENT_SUPERSEDED",
                actor=actor,
                detail={"superseded_by": document_id},
            )
        conn.execute(
            """
            UPDATE vault_documents_v22
            SET is_current=1, lifecycle_state='ACTIVE',
                verification_state='APPROVED', reviewed_by=?, reviewed_at=?
            WHERE document_id=?
            """,
            (actor, now, document_id),
        )
        _event(
            conn,
            document_id=document_id,
            document_key=document_key,
            event_type="DOCUMENT_ACTIVATED",
            actor=actor,
            detail={
                "superseded_document_id": (
                    str(prior["document_id"]) if prior is not None else ""
                )
            },
        )
    return get_document(document_id)


def list_events(document_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    initialize_vault_schema()
    document_id = identifier(document_id, "document_id")
    get_document(document_id)
    safe_limit = min(max(int(limit), 1), 1000)
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM vault_events_v22 WHERE document_id=? "
            "ORDER BY created_at DESC, event_id DESC LIMIT ?",
            (document_id, safe_limit),
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


def link_document(
    document_id: str,
    *,
    entity_type: str,
    entity_id: str,
    purpose: str,
    actor: str,
) -> dict[str, Any]:
    initialize_vault_schema()
    document_id = identifier(document_id, "document_id")
    get_document(document_id)
    entity_type = clean(entity_type, max_length=80).upper()
    entity_id = identifier(entity_id, "entity_id")
    purpose = clean(purpose, max_length=500)
    actor = clean(actor, max_length=500)
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", entity_type):
        raise ValueError("Invalid entity_type")
    if not purpose or not actor:
        raise ValueError("purpose and actor are required")
    with connection() as conn:
        existing = conn.execute(
            """
            SELECT * FROM vault_links_v22
            WHERE document_id=? AND entity_type=? AND entity_id=? AND purpose=?
            """,
            (document_id, entity_type, entity_id, purpose),
        ).fetchone()
        if existing is not None:
            return dict(existing)
        link_id = f"vlnk_{uuid.uuid4().hex}"
        linked_at = utc_now()
        conn.execute(
            """
            INSERT INTO vault_links_v22(
                link_id, document_id, entity_type, entity_id,
                purpose, linked_by, linked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                link_id,
                document_id,
                entity_type,
                entity_id,
                purpose,
                actor,
                linked_at,
            ),
        )
    return {
        "link_id": link_id,
        "document_id": document_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "purpose": purpose,
        "linked_by": actor,
        "linked_at": linked_at,
    }


def list_links(document_id: str) -> list[dict[str, Any]]:
    initialize_vault_schema()
    document_id = identifier(document_id, "document_id")
    get_document(document_id)
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM vault_links_v22 WHERE document_id=? "
            "ORDER BY linked_at DESC, link_id",
            (document_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_requirement(
    *,
    requirement_key: str,
    title: str,
    category: str,
    scope: str,
    source_reference: str,
    actor: str,
    document_key: str = "",
    required: bool = True,
    must_be_approved: bool = True,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    initialize_vault_schema()
    requirement_key = normalize_key(requirement_key, "requirement_key")
    title = clean(title, max_length=500)
    category = clean(category, max_length=80).upper()
    scope = clean(scope, max_length=80).upper()
    source_reference = clean(source_reference, max_length=2000)
    actor = clean(actor, max_length=500)
    normalized_document_key = (
        normalize_key(document_key, "document_key") if clean(document_key) else ""
    )
    if category not in CATEGORIES:
        raise ValueError(f"Invalid category: {category}")
    if scope not in REQUIREMENT_SCOPES:
        raise ValueError(f"Invalid scope: {scope}")
    if not title or not source_reference or not actor:
        raise ValueError("title, source_reference, and actor are required")
    if max_age_days is not None and not 1 <= int(max_age_days) <= 36500:
        raise ValueError("max_age_days must be between 1 and 36500")
    requirement_id = f"vreq_{uuid.uuid4().hex}"
    now = utc_now()
    with connection() as conn:
        if conn.execute(
            "SELECT 1 FROM vault_requirements_v22 WHERE requirement_key=?",
            (requirement_key,),
        ).fetchone() is not None:
            raise ValueError(f"Vault requirement already exists: {requirement_key}")
        conn.execute(
            """
            INSERT INTO vault_requirements_v22(
                requirement_id, requirement_key, title, category,
                document_key, scope, required, must_be_approved,
                max_age_days, source_reference, active,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                requirement_id,
                requirement_key,
                title,
                category,
                normalized_document_key,
                scope,
                1 if required else 0,
                1 if must_be_approved else 0,
                int(max_age_days) if max_age_days is not None else None,
                source_reference,
                actor,
                now,
                now,
            ),
        )
    return get_requirement(requirement_id)


def get_requirement(requirement_id: str) -> dict[str, Any]:
    initialize_vault_schema()
    requirement_id = identifier(requirement_id, "requirement_id")
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM vault_requirements_v22 WHERE requirement_id=?",
            (requirement_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Vault requirement not found: {requirement_id}")
    item = dict(row)
    item["required"] = bool(item["required"])
    item["must_be_approved"] = bool(item["must_be_approved"])
    item["active"] = bool(item["active"])
    return item


def list_requirements(
    *,
    scope: str | None = None,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    initialize_vault_schema()
    sql = "SELECT * FROM vault_requirements_v22 WHERE 1=1"
    params: list[Any] = []
    if scope:
        normalized = clean(scope, max_length=80).upper()
        if normalized not in REQUIREMENT_SCOPES:
            raise ValueError(f"Invalid scope: {normalized}")
        sql += " AND scope IN ('GENERAL', ?)"
        params.append(normalized)
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY required DESC, scope, category, requirement_key"
    with connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["required"] = bool(item["required"])
        item["must_be_approved"] = bool(item["must_be_approved"])
        item["active"] = bool(item["active"])
        output.append(item)
    return output


def set_requirement_active(
    requirement_id: str,
    *,
    active: bool,
    actor: str,
) -> dict[str, Any]:
    initialize_vault_schema()
    requirement_id = identifier(requirement_id, "requirement_id")
    actor = clean(actor, max_length=500)
    if not actor:
        raise ValueError("actor is required")
    now = utc_now()
    with connection() as conn:
        if conn.execute(
            "SELECT 1 FROM vault_requirements_v22 WHERE requirement_id=?",
            (requirement_id,),
        ).fetchone() is None:
            raise FileNotFoundError(f"Vault requirement not found: {requirement_id}")
        conn.execute(
            "UPDATE vault_requirements_v22 SET active=?, updated_at=? "
            "WHERE requirement_id=?",
            (1 if active else 0, now, requirement_id),
        )
    result = get_requirement(requirement_id)
    result["updated_by"] = actor
    return result
