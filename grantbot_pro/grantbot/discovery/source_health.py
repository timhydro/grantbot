from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from grantbot.core.database import connection, utc_now


FAILURE_THRESHOLD = 3
COOLDOWN_HOURS = 6


def initialize_source_health_schema() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS discovery_source_health (
                source_key TEXT PRIMARY KEY,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                last_success_at TEXT NOT NULL DEFAULT '',
                last_failure_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                last_mode TEXT NOT NULL DEFAULT '',
                last_results INTEGER NOT NULL DEFAULT 0,
                circuit_open_until TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_discovery_source_health_circuit
                ON discovery_source_health(circuit_open_until, consecutive_failures);
            """
        )


def _parse_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row(source_key: str) -> dict[str, Any] | None:
    initialize_source_health_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM discovery_source_health WHERE source_key=?",
            (source_key,),
        ).fetchone()
    return None if row is None else dict(row)


def source_available(
    source_key: str,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    record = _row(source_key)
    if record is None:
        return True, "NEW_SOURCE"
    open_until = _parse_timestamp(str(record.get("circuit_open_until", "")))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if open_until is not None and open_until > current:
        return False, f"CIRCUIT_OPEN_UNTIL_{open_until.isoformat()}"
    return True, "AVAILABLE"


def record_success(
    source_key: str,
    *,
    mode: str,
    results: int,
) -> dict[str, Any]:
    initialize_source_health_schema()
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO discovery_source_health(
                source_key, success_count, failure_count, consecutive_failures,
                last_success_at, last_failure_at, last_error, last_mode,
                last_results, circuit_open_until, updated_at
            ) VALUES (?, 1, 0, 0, ?, '', '', ?, ?, '', ?)
            ON CONFLICT(source_key) DO UPDATE SET
                success_count=discovery_source_health.success_count + 1,
                consecutive_failures=0,
                last_success_at=excluded.last_success_at,
                last_error='',
                last_mode=excluded.last_mode,
                last_results=excluded.last_results,
                circuit_open_until='',
                updated_at=excluded.updated_at
            """,
            (
                source_key,
                now,
                str(mode).upper(),
                max(0, int(results)),
                now,
            ),
        )
    return _row(source_key) or {}


def record_failure(
    source_key: str,
    *,
    mode: str,
    error: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    initialize_source_health_schema()
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current_text = current.isoformat()
    prior = _row(source_key)
    consecutive = int((prior or {}).get("consecutive_failures", 0) or 0) + 1
    circuit_open_until = ""
    if consecutive >= FAILURE_THRESHOLD:
        circuit_open_until = (current + timedelta(hours=COOLDOWN_HOURS)).isoformat()
    message = " ".join(str(error or "unknown discovery error").split())[:4000]
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO discovery_source_health(
                source_key, success_count, failure_count, consecutive_failures,
                last_success_at, last_failure_at, last_error, last_mode,
                last_results, circuit_open_until, updated_at
            ) VALUES (?, 0, 1, ?, '', ?, ?, ?, 0, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                failure_count=discovery_source_health.failure_count + 1,
                consecutive_failures=excluded.consecutive_failures,
                last_failure_at=excluded.last_failure_at,
                last_error=excluded.last_error,
                last_mode=excluded.last_mode,
                last_results=0,
                circuit_open_until=excluded.circuit_open_until,
                updated_at=excluded.updated_at
            """,
            (
                source_key,
                consecutive,
                current_text,
                message,
                str(mode).upper(),
                circuit_open_until,
                current_text,
            ),
        )
    return _row(source_key) or {}


def reset_source(source_key: str) -> dict[str, Any]:
    initialize_source_health_schema()
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO discovery_source_health(
                source_key, success_count, failure_count, consecutive_failures,
                last_success_at, last_failure_at, last_error, last_mode,
                last_results, circuit_open_until, updated_at
            ) VALUES (?, 0, 0, 0, '', '', '', '', 0, '', ?)
            ON CONFLICT(source_key) DO UPDATE SET
                consecutive_failures=0,
                last_error='',
                circuit_open_until='',
                updated_at=excluded.updated_at
            """,
            (source_key, now),
        )
    return _row(source_key) or {}


def health_summary() -> dict[str, Any]:
    initialize_source_health_schema()
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM discovery_source_health ORDER BY source_key"
        ).fetchall()
    current = datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []
    open_count = 0
    for row in rows:
        item = dict(row)
        open_until = _parse_timestamp(str(item.get("circuit_open_until", "")))
        circuit_open = bool(open_until is not None and open_until > current)
        item["circuit_open"] = circuit_open
        if circuit_open:
            open_count += 1
        records.append(item)
    return {
        "source_count": len(records),
        "circuit_open_count": open_count,
        "failure_threshold": FAILURE_THRESHOLD,
        "cooldown_hours": COOLDOWN_HOURS,
        "sources": records,
    }
