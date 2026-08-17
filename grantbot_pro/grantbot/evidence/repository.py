from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from grantbot.core.database import connection, utc_now
from grantbot.evidence.document_intelligence import (
    AUTHORITY_RANKS,
    authoritative_requirements,
    classify_authority,
    extract_requirements,
)
from grantbot.master.database import initialize_master_schema


def ingest_document(
    *,
    opportunity_id: str,
    title: str,
    pages: list[str],
    source_url: str = "",
    document_type: str = "",
    authority_type: str = "AUTO",
) -> dict[str, Any]:
    initialize_master_schema()
    opportunity_id = opportunity_id.strip()
    title = title.strip()
    if not opportunity_id:
        raise ValueError("opportunity_id is required")
    if not title:
        raise ValueError("title is required")
    if not pages or not any(page.strip() for page in pages):
        raise ValueError("at least one non-empty page is required")
    resolved = (
        classify_authority(source_url=source_url, title=title, document_type=document_type)
        if authority_type.upper() == "AUTO"
        else authority_type.upper()
    )
    if resolved not in AUTHORITY_RANKS:
        raise ValueError(f"Unknown authority_type: {resolved}")
    clean_pages = [str(page)[:500000] for page in pages]
    payload = json.dumps(clean_pages, ensure_ascii=False)
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    document_id = uuid.uuid4().hex
    created_at = utc_now()
    requirements = extract_requirements(
        opportunity_id=opportunity_id,
        pages=clean_pages,
        source_url=source_url,
        title=title,
        document_type=document_type,
        authority_type=resolved,
    )
    with connection() as conn:
        existing = conn.execute(
            """
            SELECT document_id
            FROM master_documents
            WHERE opportunity_id=? AND sha256=?
            LIMIT 1
            """,
            (opportunity_id, sha),
        ).fetchone()
        if existing is not None:
            return get_document(str(existing["document_id"]))
        conn.execute(
            """
            INSERT INTO master_documents(
                document_id, opportunity_id, title, source_url, authority_type,
                authority_rank, pages_json, sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                opportunity_id,
                title,
                source_url,
                resolved,
                AUTHORITY_RANKS[resolved],
                payload,
                sha,
                created_at,
            ),
        )
        for requirement in requirements:
            conn.execute(
                """
                INSERT INTO master_requirements(
                    requirement_id, document_id, opportunity_id, category, requirement_level,
                    text, page_number, section, authority_type, authority_rank,
                    source_url, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    requirement["requirement_id"],
                    document_id,
                    opportunity_id,
                    requirement["category"],
                    requirement["requirement_level"],
                    requirement["text"],
                    requirement["page_number"],
                    requirement["section"],
                    requirement["authority_type"],
                    requirement["authority_rank"],
                    requirement["source_url"],
                    requirement["confidence"],
                    created_at,
                ),
            )
    return {
        "document_id": document_id,
        "opportunity_id": opportunity_id,
        "title": title,
        "source_url": source_url,
        "authority_type": resolved,
        "authority_rank": AUTHORITY_RANKS[resolved],
        "sha256": sha,
        "page_count": len(clean_pages),
        "requirement_count": len(requirements),
        "requirements": requirements,
    }


def get_document(document_id: str) -> dict[str, Any]:
    initialize_master_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM master_documents WHERE document_id=?",
            (document_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Document not found: {document_id}")
        requirements = conn.execute(
            "SELECT * FROM master_requirements WHERE document_id=? ORDER BY page_number, requirement_id",
            (document_id,),
        ).fetchall()
    item = dict(row)
    try:
        pages = json.loads(str(item.pop("pages_json")))
    except json.JSONDecodeError:
        pages = []
    item["page_count"] = len(pages)
    item["requirements"] = [dict(requirement) for requirement in requirements]
    item["requirement_count"] = len(requirements)
    return item


def list_requirements(
    *,
    opportunity_id: str,
    authoritative_only: bool = True,
    category: str | None = None,
) -> list[dict[str, Any]]:
    initialize_master_schema()
    opportunity_id = opportunity_id.strip()
    if not opportunity_id:
        raise ValueError("opportunity_id is required")
    sql = "SELECT * FROM master_requirements WHERE opportunity_id=?"
    params: list[Any] = [opportunity_id]
    if category:
        sql += " AND category=?"
        params.append(category.strip().upper())
    sql += " ORDER BY authority_rank, page_number, requirement_id"
    with connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    items = [dict(row) for row in rows]
    return authoritative_requirements(items) if authoritative_only else items
