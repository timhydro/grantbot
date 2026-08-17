from __future__ import annotations

from grantbot.core.database import (
    connection,
    utc_now,
)
from grantbot.core.utils import (
    safe_json_dumps,
    safe_json_loads,
)
from grantbot.discovery.schema import (
    initialize_discovery_schema,
)
from grantbot.funding.registry import (
    get_source,
)


def add_page(
    *,
    source_key: str,
    url: str,
    page_name: str | None = None,
    page_type: str = "HTML",
    respect_robots: bool = True,
    max_links: int = 100,
    metadata: dict | None = None,
) -> dict:
    initialize_discovery_schema()
    source = get_source(source_key)
    if not source:
        raise ValueError(f"Unknown funding source: {source_key}")

    page_type = page_type.upper()
    if page_type not in {"HTML", "RSS", "JSON"}:
        raise ValueError("page_type must be HTML, RSS, or JSON")

    now = utc_now()
    with connection() as conn:
        existing = conn.execute(
            "SELECT id FROM discovery_source_pages WHERE url=?",
            (url,),
        ).fetchone()
        if existing:
            page_id = existing["id"]
            conn.execute(
                """
                UPDATE discovery_source_pages
                SET source_id=?, page_name=?, page_type=?, active=1,
                    respect_robots=?, max_links=?, metadata_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    source["id"],
                    page_name,
                    page_type,
                    1 if respect_robots else 0,
                    int(max_links),
                    safe_json_dumps(metadata or {}),
                    now,
                    page_id,
                ),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO discovery_source_pages(
                    source_id, page_name, page_type, url, active,
                    respect_robots, max_links, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    source["id"],
                    page_name,
                    page_type,
                    url,
                    1 if respect_robots else 0,
                    int(max_links),
                    safe_json_dumps(metadata or {}),
                    now,
                    now,
                ),
            )
            page_id = cursor.lastrowid

    return get_page(page_id)


def get_page(page_id: int) -> dict | None:
    initialize_discovery_schema()
    with connection() as conn:
        row = conn.execute(
            """
            SELECT p.*, sp.source_key, fs.source_name
            FROM discovery_source_pages p
            JOIN funding_source_profiles sp ON sp.source_id=p.source_id
            JOIN funding_sources fs ON fs.id=p.source_id
            WHERE p.id=?
            """,
            (page_id,),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["metadata"] = safe_json_loads(
        result.get("metadata_json"),
        {},
    )
    return result


def list_pages(
    source_key: str | None = None,
    *,
    active_only: bool = True,
) -> list[dict]:
    initialize_discovery_schema()
    sql = """
        SELECT p.*, sp.source_key, fs.source_name
        FROM discovery_source_pages p
        JOIN funding_source_profiles sp ON sp.source_id=p.source_id
        JOIN funding_sources fs ON fs.id=p.source_id
        WHERE 1=1
    """
    params: list[str] = []
    if source_key:
        sql += " AND sp.source_key=?"
        params.append(source_key)
    if active_only:
        sql += " AND p.active=1"
    sql += " ORDER BY sp.source_key, p.page_name, p.url"

    with connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    results: list[dict] = []
    for row in rows:
        record = dict(row)
        record["metadata"] = safe_json_loads(
            record.get("metadata_json"),
            {},
        )
        results.append(record)
    return results


def remove_page(page_id: int) -> bool:
    initialize_discovery_schema()
    with connection() as conn:
        cursor = conn.execute(
            "DELETE FROM discovery_source_pages WHERE id=?",
            (page_id,),
        )
        return cursor.rowcount > 0
