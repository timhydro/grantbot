from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from grantbot.core.database import connection, utc_now
from grantbot.discovery.engine import DiscoveryEngine
from grantbot.discovery.pages import list_pages
from grantbot.discovery.source_health import (
    health_summary,
    record_failure,
    record_success,
    source_available,
)
from grantbot.funding.planner import build_discovery_plan
from grantbot.funding.registry import get_source, seed_catalog


@dataclass(frozen=True, slots=True)
class DiscoveryCampaignResult:
    campaign_id: str
    status: str
    plan_count: int
    attempted_count: int
    skipped_count: int
    seen_count: int
    saved_count: int
    duplicate_count: int
    error_count: int
    items: list[dict[str, Any]]
    started_at: str
    finished_at: str
    actor: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def initialize_campaign_schema() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS discovery_campaigns (
                campaign_id TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                state TEXT NOT NULL,
                counties_json TEXT NOT NULL,
                cities_json TEXT NOT NULL,
                lanes_json TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                plan_count INTEGER NOT NULL,
                attempted_count INTEGER NOT NULL,
                skipped_count INTEGER NOT NULL,
                seen_count INTEGER NOT NULL,
                saved_count INTEGER NOT NULL,
                duplicate_count INTEGER NOT NULL,
                error_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_discovery_campaigns_started
                ON discovery_campaigns(started_at DESC);
            """
        )


def _clean_list(values: list[str] | None) -> list[str]:
    output: list[str] = []
    for value in values or []:
        text = " ".join(str(value).split()).strip()
        if text and text not in output:
            output.append(text)
    return output


def _campaign_plan(
    *,
    state: str,
    counties: list[str] | None,
    cities: list[str] | None,
    lanes: list[str] | None,
    max_queries: int,
    include_conditional: bool,
    include_investment: bool,
    include_subscription: bool,
) -> list[dict[str, Any]]:
    seed_catalog()
    raw = build_discovery_plan(
        state=state,
        counties=_clean_list(counties),
        cities=_clean_list(cities),
        lanes=_clean_list(lanes) or None,
    )
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in raw:
        source_key = str(row.get("source_key", ""))
        source = get_source(source_key)
        if source is None:
            continue
        fit = str(source.get("nonprofit_fit", "DIRECT")).upper()
        if not include_conditional and fit != "DIRECT":
            continue
        if not include_investment and bool(source.get("requires_investable_entity")):
            continue
        if not include_subscription and bool(source.get("requires_subscription")):
            continue
        key = (
            source_key,
            str(row.get("lane", "")),
            str(row.get("query", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        enriched = dict(row)
        enriched["source_fit"] = fit
        enriched["requires_subscription"] = bool(source.get("requires_subscription"))
        enriched["requires_investable_entity"] = bool(
            source.get("requires_investable_entity")
        )
        enriched["requires_legal_review"] = bool(source.get("requires_legal_review"))
        selected.append(enriched)
        if len(selected) >= max_queries:
            break
    return selected


def plan_discovery_campaign(
    *,
    state: str = "Florida",
    counties: list[str] | None = None,
    cities: list[str] | None = None,
    lanes: list[str] | None = None,
    max_queries: int = 25,
    include_conditional: bool = True,
    include_investment: bool = True,
    include_subscription: bool = False,
) -> dict[str, Any]:
    if not 1 <= int(max_queries) <= 100:
        raise ValueError("max_queries must be between 1 and 100")
    plan = _campaign_plan(
        state=" ".join(str(state).split()).strip() or "Florida",
        counties=counties,
        cities=cities,
        lanes=lanes,
        max_queries=int(max_queries),
        include_conditional=include_conditional,
        include_investment=include_investment,
        include_subscription=include_subscription,
    )
    return {
        "state": state,
        "counties": _clean_list(counties),
        "cities": _clean_list(cities),
        "lanes": _clean_list(lanes),
        "query_count": len(plan),
        "plan": plan,
    }


def _execution_mode(
    engine: DiscoveryEngine,
    row: dict[str, Any],
    *,
    broad_web: bool,
) -> tuple[str, str]:
    source_key = str(row["source_key"])
    if source_key == "federal_grants_gov":
        return "GRANTS_GOV", "DEDICATED_API"
    pages = list_pages(source_key)
    if pages:
        return "REGISTERED_PAGES", f"{len(pages)}_REGISTERED_PAGE(S)"
    if broad_web and engine.brave.enabled:
        return "BROAD_WEB", "BRAVE_SEARCH"
    if broad_web:
        return "SKIP", "NO_REGISTERED_PAGE_AND_BRAVE_NOT_CONFIGURED"
    return "SKIP", "NO_REGISTERED_PAGE_AND_BROAD_WEB_DISABLED"


def _result_sample(stats: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in list(stats.get("results", []))[:limit]:
        if not isinstance(item, dict):
            continue
        output.append(
            {
                "opportunity_id": item.get("opportunity_id"),
                "title": item.get("title"),
                "source_url": item.get("source_url"),
                "deadline": item.get("deadline"),
                "duplicate": bool(item.get("duplicate", False)),
            }
        )
    return output


def run_discovery_campaign(
    *,
    state: str = "Florida",
    counties: list[str] | None = None,
    cities: list[str] | None = None,
    lanes: list[str] | None = None,
    max_queries: int = 25,
    per_query_limit: int = 10,
    broad_web: bool = True,
    include_conditional: bool = True,
    include_investment: bool = True,
    include_subscription: bool = False,
    actor: str,
    engine: DiscoveryEngine | None = None,
) -> DiscoveryCampaignResult:
    actor = " ".join(str(actor).split()).strip()
    if not actor:
        raise ValueError("actor is required")
    if not 1 <= int(per_query_limit) <= 25:
        raise ValueError("per_query_limit must be between 1 and 25")
    plan_payload = plan_discovery_campaign(
        state=state,
        counties=counties,
        cities=cities,
        lanes=lanes,
        max_queries=max_queries,
        include_conditional=include_conditional,
        include_investment=include_investment,
        include_subscription=include_subscription,
    )
    plan = list(plan_payload["plan"])
    runner = engine or DiscoveryEngine()
    campaign_id = uuid.uuid4().hex
    started_at = utc_now()
    attempted = 0
    skipped = 0
    seen = 0
    saved = 0
    duplicates = 0
    errors = 0
    items: list[dict[str, Any]] = []

    for row in plan:
        source_key = str(row["source_key"])
        available, availability_reason = source_available(source_key)
        if not available:
            skipped += 1
            items.append(
                {
                    "source_key": source_key,
                    "lane": row.get("lane"),
                    "query": row.get("query"),
                    "status": "SKIPPED",
                    "reason": availability_reason,
                }
            )
            continue

        mode, mode_reason = _execution_mode(runner, row, broad_web=broad_web)
        if mode == "SKIP":
            skipped += 1
            items.append(
                {
                    "source_key": source_key,
                    "lane": row.get("lane"),
                    "query": row.get("query"),
                    "status": "SKIPPED",
                    "reason": mode_reason,
                }
            )
            continue

        attempted += 1
        try:
            if mode == "GRANTS_GOV":
                stats = runner.grants_gov(
                    query=str(row["query"]),
                    limit=int(per_query_limit),
                    detail_limit=min(int(per_query_limit), 10),
                    save=True,
                    lane=str(row.get("lane") or ""),
                )
            elif mode == "REGISTERED_PAGES":
                stats = runner.crawl_registered_pages(
                    source_key=source_key,
                    query=str(row["query"]),
                    geography=str(row.get("geography") or ""),
                    limit=int(per_query_limit),
                    save=True,
                    lane=str(row.get("lane") or ""),
                )
            else:
                stats = runner.broad_web_search(
                    plan_row=row,
                    count=min(int(per_query_limit), 20),
                    save=True,
                    max_pages=min(int(per_query_limit), 6),
                )

            row_seen = int(stats.get("seen", 0) or 0)
            row_saved = int(stats.get("saved", 0) or 0)
            row_duplicates = int(stats.get("duplicates", 0) or 0)
            row_errors = int(stats.get("errors", 0) or 0)
            seen += row_seen
            saved += row_saved
            duplicates += row_duplicates
            errors += row_errors
            if row_errors:
                record_failure(
                    source_key,
                    mode=mode,
                    error=f"Discovery run reported {row_errors} error(s)",
                )
            else:
                record_success(source_key, mode=mode, results=row_seen)
            items.append(
                {
                    "source_key": source_key,
                    "source_name": row.get("source_name"),
                    "lane": row.get("lane"),
                    "query": row.get("query"),
                    "mode": mode,
                    "status": "COMPLETE" if row_errors == 0 else "PARTIAL",
                    "seen": row_seen,
                    "saved": row_saved,
                    "duplicates": row_duplicates,
                    "errors": row_errors,
                    "results": _result_sample(stats),
                }
            )
        except Exception as exc:
            errors += 1
            record_failure(source_key, mode=mode, error=str(exc))
            items.append(
                {
                    "source_key": source_key,
                    "source_name": row.get("source_name"),
                    "lane": row.get("lane"),
                    "query": row.get("query"),
                    "mode": mode,
                    "status": "ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    if attempted == 0:
        status = "NO_EXECUTABLE_SOURCES"
    elif errors == 0:
        status = "COMPLETE"
    elif errors < attempted:
        status = "PARTIAL"
    else:
        status = "FAILED"

    finished_at = utc_now()
    result = DiscoveryCampaignResult(
        campaign_id=campaign_id,
        status=status,
        plan_count=len(plan),
        attempted_count=attempted,
        skipped_count=skipped,
        seen_count=seen,
        saved_count=saved,
        duplicate_count=duplicates,
        error_count=errors,
        items=items,
        started_at=started_at,
        finished_at=finished_at,
        actor=actor,
    )
    initialize_campaign_schema()
    payload = result.to_dict()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO discovery_campaigns(
                campaign_id, actor, state, counties_json, cities_json,
                lanes_json, settings_json, plan_count, attempted_count,
                skipped_count, seen_count, saved_count, duplicate_count,
                error_count, status, result_json, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                actor,
                str(state),
                json.dumps(_clean_list(counties), ensure_ascii=False),
                json.dumps(_clean_list(cities), ensure_ascii=False),
                json.dumps(_clean_list(lanes), ensure_ascii=False),
                json.dumps(
                    {
                        "max_queries": int(max_queries),
                        "per_query_limit": int(per_query_limit),
                        "broad_web": bool(broad_web),
                        "include_conditional": bool(include_conditional),
                        "include_investment": bool(include_investment),
                        "include_subscription": bool(include_subscription),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                len(plan),
                attempted,
                skipped,
                seen,
                saved,
                duplicates,
                errors,
                status,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                started_at,
                finished_at,
            ),
        )
    return result


def get_campaign(campaign_id: str) -> dict[str, Any]:
    initialize_campaign_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT result_json FROM discovery_campaigns WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Discovery campaign not found: {campaign_id}")
    try:
        payload = json.loads(str(row["result_json"]))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Stored discovery campaign result is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Stored discovery campaign result is not an object")
    return payload


def recent_campaigns(limit: int = 20) -> list[dict[str, Any]]:
    initialize_campaign_schema()
    safe_limit = min(max(int(limit), 1), 100)
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT campaign_id, actor, state, plan_count, attempted_count,
                   skipped_count, seen_count, saved_count, duplicate_count,
                   error_count, status, started_at, finished_at
            FROM discovery_campaigns
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def discovery_health() -> dict[str, Any]:
    summary = health_summary()
    summary["campaigns"] = recent_campaigns(limit=10)
    return summary
