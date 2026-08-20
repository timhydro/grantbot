from __future__ import annotations

from typing import Any

from grantbot.core.database import audit, connection, fetch_all, fetch_one, utc_now
from grantbot.core.utils import safe_json_dumps, safe_json_loads
from grantbot.funding.catalog import SOURCE_CATALOG
from grantbot.funding.extended_catalog import EXTENDED_SOURCE_CATALOG
from grantbot.funding.investor_catalog import INVESTOR_SOURCE_CATALOG
from grantbot.funding.schema import initialize_funding_schema


def _bool(value: Any) -> int:
    return 1 if bool(value) else 0


def register_source(
    *,
    source_key: str,
    source_name: str,
    source_kind: str,
    jurisdiction: str,
    geography: str,
    mechanisms: list[str],
    issue_areas: list[str] | None = None,
    access_methods: list[str] | None = None,
    applicant_types: list[str] | None = None,
    website: str | None = None,
    api_endpoint: str | None = None,
    nonprofit_fit: str = "DIRECT",
    requires_investable_entity: bool = False,
    requires_legal_review: bool = False,
    requires_subscription: bool = False,
    search_priority: int = 50,
    notes: str | None = None,
) -> dict[str, Any]:
    initialize_funding_schema()
    source_key = source_key.strip().lower()
    if not source_key:
        raise ValueError("source_key is required")
    if not source_name.strip():
        raise ValueError("source_name is required")

    with connection() as conn:
        row = conn.execute(
            """
            SELECT fs.id
            FROM funding_sources fs
            JOIN funding_source_profiles p ON p.source_id = fs.id
            WHERE p.source_key=?
            """,
            (source_key,),
        ).fetchone()
        now = utc_now()

        if row:
            source_id = int(row["id"])
            conn.execute(
                """
                UPDATE funding_sources
                SET source_type=?, source_name=?, jurisdiction_level=?, geography=?,
                    website=?, api_endpoint=?, active=1, updated_at=?
                WHERE id=?
                """,
                (source_kind, source_name, jurisdiction, geography, website, api_endpoint, now, source_id),
            )
            conn.execute(
                """
                UPDATE funding_source_profiles
                SET source_kind=?, mechanisms_json=?, applicant_types_json=?, issue_areas_json=?,
                    access_methods_json=?, nonprofit_fit=?, requires_investable_entity=?,
                    requires_legal_review=?, requires_subscription=?, search_priority=?, notes=?
                WHERE source_id=?
                """,
                (
                    source_kind,
                    safe_json_dumps(mechanisms),
                    safe_json_dumps(applicant_types or []),
                    safe_json_dumps(issue_areas or []),
                    safe_json_dumps(access_methods or []),
                    nonprofit_fit,
                    _bool(requires_investable_entity),
                    _bool(requires_legal_review),
                    _bool(requires_subscription),
                    int(search_priority),
                    notes,
                    source_id,
                ),
            )
            action = "funding_source.updated"
        else:
            cursor = conn.execute(
                """
                INSERT INTO funding_sources(
                    source_type, source_name, jurisdiction_level, geography, website,
                    api_endpoint, active, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (source_kind, source_name, jurisdiction, geography, website, api_endpoint, "{}", now, now),
            )
            source_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO funding_source_profiles(
                    source_id, source_key, source_kind, mechanisms_json, applicant_types_json,
                    issue_areas_json, access_methods_json, nonprofit_fit, requires_investable_entity,
                    requires_legal_review, requires_subscription, search_priority, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    source_key,
                    source_kind,
                    safe_json_dumps(mechanisms),
                    safe_json_dumps(applicant_types or []),
                    safe_json_dumps(issue_areas or []),
                    safe_json_dumps(access_methods or []),
                    nonprofit_fit,
                    _bool(requires_investable_entity),
                    _bool(requires_legal_review),
                    _bool(requires_subscription),
                    int(search_priority),
                    notes,
                ),
            )
            action = "funding_source.created"

    audit(
        action,
        entity_type="funding_source",
        entity_id=source_id,
        details={"source_key": source_key, "source_name": source_name, "source_kind": source_kind},
    )
    result = get_source(source_key)
    if result is None:
        raise RuntimeError(f"Funding source registration failed: {source_key}")
    return result


def seed_catalog() -> int:
    count = 0
    for source in [*SOURCE_CATALOG, *EXTENDED_SOURCE_CATALOG, *INVESTOR_SOURCE_CATALOG]:
        register_source(**source)
        count += 1
    return count


def get_source(source_key: str) -> dict[str, Any] | None:
    row = fetch_one(
        """
        SELECT fs.*, p.source_key, p.source_kind, p.mechanisms_json, p.applicant_types_json,
               p.issue_areas_json, p.access_methods_json, p.nonprofit_fit, p.requires_investable_entity,
               p.requires_legal_review, p.requires_subscription, p.search_priority, p.notes
        FROM funding_sources fs
        JOIN funding_source_profiles p ON p.source_id=fs.id
        WHERE p.source_key=?
        """,
        (source_key.strip().lower(),),
    )
    return decode_source(row) if row else None


def list_sources(
    *,
    active_only: bool = True,
    source_kind: str | None = None,
    jurisdiction: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT fs.*, p.source_key, p.source_kind, p.mechanisms_json, p.applicant_types_json,
               p.issue_areas_json, p.access_methods_json, p.nonprofit_fit, p.requires_investable_entity,
               p.requires_legal_review, p.requires_subscription, p.search_priority, p.notes
        FROM funding_sources fs
        JOIN funding_source_profiles p ON p.source_id=fs.id
        WHERE 1=1
    """
    params: list[Any] = []
    if active_only:
        sql += " AND fs.active=1"
    if source_kind:
        sql += " AND p.source_kind=?"
        params.append(source_kind)
    if jurisdiction:
        sql += " AND fs.jurisdiction_level=?"
        params.append(jurisdiction)
    sql += " ORDER BY p.search_priority DESC, fs.source_name ASC"
    return [decode_source(row) for row in fetch_all(sql, tuple(params))]


def registry_stats() -> dict[str, Any]:
    sources = list_sources(active_only=False)
    kinds: dict[str, int] = {}
    jurisdictions: dict[str, int] = {}
    active = 0
    direct = 0
    conditional = 0
    investable_entity_required = 0

    for source in sources:
        kind = str(source.get("source_kind") or "UNKNOWN")
        jurisdiction = str(source.get("jurisdiction_level") or "UNKNOWN")
        kinds[kind] = kinds.get(kind, 0) + 1
        jurisdictions[jurisdiction] = jurisdictions.get(jurisdiction, 0) + 1
        if source.get("active"):
            active += 1
        fit = str(source.get("nonprofit_fit") or "")
        if fit == "DIRECT":
            direct += 1
        elif fit == "CONDITIONAL":
            conditional += 1
        if source.get("requires_investable_entity"):
            investable_entity_required += 1

    by_kind = dict(sorted(kinds.items()))
    by_jurisdiction = dict(sorted(jurisdictions.items()))
    return {
        "total_sources": len(sources),
        "active_sources": active,
        "direct_nonprofit_sources": direct,
        "conditional_sources": conditional,
        "investable_entity_required": investable_entity_required,
        "source_kinds": by_kind,
        "jurisdictions": by_jurisdiction,
        # Compatibility aliases retained for older API/tests and external clients.
        "by_source_kind": by_kind,
        "by_jurisdiction": by_jurisdiction,
    }


def decode_source(row: Any) -> dict[str, Any]:
    item = dict(row)
    for source_key, target_key in (
        ("mechanisms_json", "mechanisms"),
        ("applicant_types_json", "applicant_types"),
        ("issue_areas_json", "issue_areas"),
        ("access_methods_json", "access_methods"),
    ):
        item[target_key] = safe_json_loads(item.get(source_key), default=[])
    for key in ("requires_investable_entity", "requires_legal_review", "requires_subscription", "active"):
        item[key] = bool(item.get(key))
    return item
