from __future__ import annotations

from grantbot.core.database import (
    fetch_all,
    fetch_one,
)


def discovery_stats() -> dict:

    opportunity_count = fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM opportunities
        """
    )["n"]

    source_counts = fetch_all(
        """
        SELECT
            COALESCE(
                p.source_key,
                'unknown'
            ) AS source_key,

            COUNT(o.id) AS opportunities

        FROM opportunities o

        LEFT JOIN funding_source_profiles p
          ON p.source_id=o.funding_source_id

        GROUP BY
            p.source_key

        ORDER BY
            opportunities DESC
        """
    )

    run_count = fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM discovery_runs
        """
    )["n"]

    latest_runs = fetch_all(
        """
        SELECT *
        FROM discovery_runs
        ORDER BY id DESC
        LIMIT 10
        """
    )

    page_count = fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM discovery_source_pages
        WHERE active=1
        """
    )["n"]

    return {
        "opportunities":
            opportunity_count,

        "registered_live_pages":
            page_count,

        "discovery_runs":
            run_count,

        "by_source":
            source_counts,

        "latest_runs":
            latest_runs,
    }
