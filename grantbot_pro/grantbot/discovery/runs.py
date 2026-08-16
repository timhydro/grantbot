from __future__ import annotations

from grantbot.core.database import (
    connection,
    utc_now,
)

from grantbot.core.utils import (
    safe_json_dumps,
)


def start_run(
    mode: str,
    metadata: dict | None = None,
) -> int:

    with connection() as conn:

        cursor = conn.execute(
            """
            INSERT INTO discovery_runs(
                mode,
                started_at,
                metadata_json
            )
            VALUES (?, ?, ?)
            """,
            (
                mode,
                utc_now(),
                safe_json_dumps(
                    metadata
                    or {}
                ),
            ),
        )

        return int(
            cursor.lastrowid
        )


def finish_run(
    run_id: int,
    *,
    sources_attempted: int,
    queries_attempted: int,
    results_seen: int,
    opportunities_saved: int,
    duplicates_skipped: int,
    errors: int,
) -> None:

    with connection() as conn:

        conn.execute(
            """
            UPDATE discovery_runs
            SET
                finished_at=?,
                sources_attempted=?,
                queries_attempted=?,
                results_seen=?,
                opportunities_saved=?,
                duplicates_skipped=?,
                errors=?
            WHERE id=?
            """,
            (
                utc_now(),
                sources_attempted,
                queries_attempted,
                results_seen,
                opportunities_saved,
                duplicates_skipped,
                errors,
                run_id,
            ),
        )


def event(
    run_id: int,
    *,
    event_type: str,
    source_key: str | None = None,
    query_text: str | None = None,
    message: str | None = None,
    metadata: dict | None = None,
) -> None:

    with connection() as conn:

        conn.execute(
            """
            INSERT INTO discovery_events(
                run_id,
                source_key,
                query_text,
                event_type,
                message,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                source_key,
                query_text,
                event_type,
                message,
                safe_json_dumps(
                    metadata
                    or {}
                ),
                utc_now(),
            ),
        )
