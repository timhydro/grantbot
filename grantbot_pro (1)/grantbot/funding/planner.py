from __future__ import annotations

from itertools import product

from grantbot.core.database import (
    connection,
    utc_now,
)

from grantbot.core.utils import (
    safe_json_dumps,
)

from grantbot.funding.lanes import (
    DEFAULT_PRIORITY_LANES,
    SEARCH_LANES,
)

from grantbot.funding.registry import (
    list_sources,
)

from grantbot.investors.structure_guard import (
    analyze_source_structure,
)


LANE_SOURCE_MAP = {

    "reentry": {
        "GOVERNMENT",
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "FAMILY_FOUNDATION",
        "FAITH_BASED",
        "WORKFORCE_BOARD",
    },

    "housing": {
        "GOVERNMENT",
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "BANK",
        "CDFI",
        "COMMUNITY_REDEVELOPMENT",
        "CONTINUUM_OF_CARE",
        "IMPACT_INVESTOR",
        "PHILANTHROPIC_INVESTOR",
    },

    "homelessness": {
        "GOVERNMENT",
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "FAITH_BASED",
        "CONTINUUM_OF_CARE",
    },

    "workforce": {
        "GOVERNMENT",
        "WORKFORCE_BOARD",
        "FOUNDATION",
        "CORPORATE",
        "BANK",
        "IMPACT_INVESTOR",
    },

    "community_development": {
        "GOVERNMENT",
        "COMMUNITY_REDEVELOPMENT",
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "BANK",
        "CDFI",
        "IMPACT_INVESTOR",
    },

    "capital": {
        "GOVERNMENT",
        "FOUNDATION",
        "BANK",
        "CDFI",
        "FAITH_BASED",
        "CHURCH",
        "SPONSOR",
        "IMPACT_INVESTOR",
        "PHILANTHROPIC_INVESTOR",
    },

    "economic_development": {
        "GOVERNMENT",
        "COMMUNITY_REDEVELOPMENT",
        "BANK",
        "CDFI",
        "CORPORATE",
        "IMPACT_INVESTOR",
        "ANGEL_NETWORK",
    },

    "foundation": {
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "FAMILY_FOUNDATION",
    },

    "faith": {
        "FAITH_BASED",
        "CHURCH",
    },

    "corporate": {
        "CORPORATE",
        "SPONSOR",
    },

    "bank_cra": {
        "BANK",
        "CDFI",
    },

    "investor": {
        "ANGEL_NETWORK",
        "ANGEL_INVESTOR",
        "IMPACT_INVESTOR",
        "IMPACT_FUND",
        "PHILANTHROPIC_INVESTOR",
    },
}


def _source_matches_lane(
    source: dict,
    lane: str,
) -> bool:

    allowed = LANE_SOURCE_MAP.get(
        lane
    )

    if not allowed:
        return True

    return (
        source.get(
            "source_kind"
        )
        in allowed
    )


def build_discovery_plan(
    *,
    state: str = "Florida",
    counties: list[str] | None = None,
    cities: list[str] | None = None,
    lanes: list[str] | None = None,
    max_terms_per_lane: int = 4,
) -> list[dict]:

    counties = [
        c.strip()
        for c in (
            counties or []
        )
        if c.strip()
    ]

    cities = [
        c.strip()
        for c in (
            cities or []
        )
        if c.strip()
    ]

    lanes = (
        lanes
        or DEFAULT_PRIORITY_LANES
    )

    sources = list_sources()

    plan = []

    for lane in lanes:

        terms = SEARCH_LANES.get(
            lane,
            []
        )[:max_terms_per_lane]

        for source in sources:

            if not _source_matches_lane(
                source,
                lane,
            ):
                continue

            jurisdiction = (
                source.get(
                    "jurisdiction_level"
                )
                or ""
            )

            geographies = []

            if jurisdiction == "COUNTY":
                geographies = [
                    f"{county} County, {state}"
                    for county in counties
                ]

                if not geographies:
                    geographies = [
                        state
                    ]

            elif jurisdiction in {
                "CITY",
                "MUNICIPAL",
            }:
                geographies = [
                    f"{city}, {state}"
                    for city in cities
                ]

                if not geographies:
                    geographies = [
                        state
                    ]

            elif jurisdiction in {
                "STATE",
                "LOCAL",
                "REGIONAL",
            }:
                geographies = [
                    state
                ]

            else:
                geographies = [
                    source.get(
                        "geography"
                    )
                    or state
                ]

            structure = (
                analyze_source_structure(
                    source
                )
            )

            for term, geography in product(
                terms,
                geographies,
            ):
                query = (
                    f"{term} "
                    f"{geography}"
                ).strip()

                plan.append({
                    "source_id":
                        source["id"],

                    "source_key":
                        source[
                            "source_key"
                        ],

                    "source_name":
                        source[
                            "source_name"
                        ],

                    "source_kind":
                        source[
                            "source_kind"
                        ],

                    "jurisdiction":
                        jurisdiction,

                    "lane":
                        lane,

                    "query":
                        query,

                    "geography":
                        geography,

                    "priority":
                        source.get(
                            "search_priority",
                            50,
                        ),

                    "nonprofit_fit":
                        source.get(
                            "nonprofit_fit"
                        ),

                    "requires_legal_review":
                        structure[
                            "requires_legal_review"
                        ],

                    "requires_investable_entity":
                        structure[
                            "requires_investable_entity"
                        ],

                    "warnings":
                        structure[
                            "warnings"
                        ],
                })

    plan.sort(
        key=lambda row: (
            -row["priority"],
            row[
                "requires_legal_review"
            ],
            row["lane"],
            row["source_name"],
            row["query"],
        )
    )

    return plan


def save_plan(
    plan: list[dict],
) -> int:

    with connection() as conn:

        conn.execute(
            """
            DELETE FROM funding_queries
            WHERE status='PLANNED'
            """
        )

        for row in plan:
            conn.execute(
                """
                INSERT INTO funding_queries(
                    source_id,
                    query_text,
                    lane,
                    geography,
                    status,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, 'PLANNED', ?, ?)
                """,
                (
                    row["source_id"],
                    row["query"],
                    row["lane"],
                    row["geography"],
                    safe_json_dumps({
                        "priority":
                            row[
                                "priority"
                            ],

                        "source_key":
                            row[
                                "source_key"
                            ],

                        "nonprofit_fit":
                            row[
                                "nonprofit_fit"
                            ],

                        "requires_legal_review":
                            row[
                                "requires_legal_review"
                            ],

                        "requires_investable_entity":
                            row[
                                "requires_investable_entity"
                            ],

                        "warnings":
                            row[
                                "warnings"
                            ],
                    }),
                    utc_now(),
                ),
            )

    return len(plan)
