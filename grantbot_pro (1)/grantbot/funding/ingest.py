from __future__ import annotations

import json
from typing import Any

from grantbot.core.database import (
    audit,
    connection,
    utc_now,
)

from grantbot.core.utils import (
    normalize_text,
    safe_json_dumps,
)

from grantbot.funding.registry import (
    get_source,
)


def normalize_opportunity(
    payload: dict[str, Any],
) -> dict[str, Any]:

    title = normalize_text(
        payload.get(
            "title"
        )
    )

    if not title:
        raise ValueError(
            "Opportunity requires a title."
        )

    return {
        "external_id":
            normalize_text(
                payload.get(
                    "external_id"
                )
            )
            or None,

        "opportunity_type":
            normalize_text(
                payload.get(
                    "opportunity_type"
                )
            ).upper()
            or "GRANT",

        "title":
            title,

        "funder":
            normalize_text(
                payload.get(
                    "funder"
                )
            )
            or None,

        "agency":
            normalize_text(
                payload.get(
                    "agency"
                )
            )
            or None,

        "description":
            normalize_text(
                payload.get(
                    "description"
                )
            )
            or None,

        "eligibility":
            normalize_text(
                payload.get(
                    "eligibility"
                )
            )
            or None,

        "geography":
            normalize_text(
                payload.get(
                    "geography"
                )
            )
            or None,

        "opening_date":
            normalize_text(
                payload.get(
                    "opening_date"
                )
            )
            or None,

        "deadline":
            normalize_text(
                payload.get(
                    "deadline"
                )
            )
            or None,

        "award_floor":
            payload.get(
                "award_floor"
            ),

        "award_ceiling":
            payload.get(
                "award_ceiling"
            ),

        "estimated_total":
            payload.get(
                "estimated_total"
            ),

        "opportunity_number":
            normalize_text(
                payload.get(
                    "opportunity_number"
                )
            )
            or None,

        "assistance_listing":
            normalize_text(
                payload.get(
                    "assistance_listing"
                )
            )
            or None,

        "source_url":
            normalize_text(
                payload.get(
                    "source_url"
                )
            )
            or None,

        "status":
            normalize_text(
                payload.get(
                    "status"
                )
            ).upper()
            or "DISCOVERED",

        "raw_json":
            safe_json_dumps(
                payload
            ),
    }


def ingest_opportunity(
    source_key: str,
    payload: dict[str, Any],
) -> int:

    source = get_source(
        source_key
    )

    if not source:
        raise ValueError(
            f"Unknown funding source: "
            f"{source_key}"
        )

    row = normalize_opportunity(
        payload
    )

    now = utc_now()

    with connection() as conn:

        existing = None

        if row["external_id"]:
            existing = conn.execute(
                """
                SELECT id
                FROM opportunities
                WHERE
                    external_id=?
                    AND funding_source_id=?
                """,
                (
                    row[
                        "external_id"
                    ],
                    source["id"],
                ),
            ).fetchone()

        if existing:

            opportunity_id = (
                existing["id"]
            )

            conn.execute(
                """
                UPDATE opportunities
                SET
                    opportunity_type=?,
                    title=?,
                    funder=?,
                    agency=?,
                    description=?,
                    eligibility=?,
                    geography=?,
                    opening_date=?,
                    deadline=?,
                    award_floor=?,
                    award_ceiling=?,
                    estimated_total=?,
                    opportunity_number=?,
                    assistance_listing=?,
                    source_url=?,
                    status=?,
                    raw_json=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    row[
                        "opportunity_type"
                    ],
                    row["title"],
                    row["funder"],
                    row["agency"],
                    row[
                        "description"
                    ],
                    row[
                        "eligibility"
                    ],
                    row[
                        "geography"
                    ],
                    row[
                        "opening_date"
                    ],
                    row[
                        "deadline"
                    ],
                    row[
                        "award_floor"
                    ],
                    row[
                        "award_ceiling"
                    ],
                    row[
                        "estimated_total"
                    ],
                    row[
                        "opportunity_number"
                    ],
                    row[
                        "assistance_listing"
                    ],
                    row[
                        "source_url"
                    ],
                    row["status"],
                    row[
                        "raw_json"
                    ],
                    now,
                    opportunity_id,
                ),
            )

            action = (
                "opportunity.updated"
            )

        else:

            cursor = conn.execute(
                """
                INSERT INTO opportunities(
                    external_id,
                    funding_source_id,
                    opportunity_type,
                    title,
                    funder,
                    agency,
                    description,
                    eligibility,
                    geography,
                    opening_date,
                    deadline,
                    award_floor,
                    award_ceiling,
                    estimated_total,
                    opportunity_number,
                    assistance_listing,
                    source_url,
                    status,
                    raw_json,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    row[
                        "external_id"
                    ],
                    source["id"],
                    row[
                        "opportunity_type"
                    ],
                    row["title"],
                    row["funder"],
                    row["agency"],
                    row[
                        "description"
                    ],
                    row[
                        "eligibility"
                    ],
                    row[
                        "geography"
                    ],
                    row[
                        "opening_date"
                    ],
                    row[
                        "deadline"
                    ],
                    row[
                        "award_floor"
                    ],
                    row[
                        "award_ceiling"
                    ],
                    row[
                        "estimated_total"
                    ],
                    row[
                        "opportunity_number"
                    ],
                    row[
                        "assistance_listing"
                    ],
                    row[
                        "source_url"
                    ],
                    row[
                        "status"
                    ],
                    row[
                        "raw_json"
                    ],
                    now,
                    now,
                ),
            )

            opportunity_id = (
                cursor.lastrowid
            )

            action = (
                "opportunity.created"
            )

    audit(
        action,
        entity_type="opportunity",
        entity_id=opportunity_id,
        details={
            "source_key":
                source_key,

            "title":
                row["title"],
        },
    )

    return int(
        opportunity_id
    )
