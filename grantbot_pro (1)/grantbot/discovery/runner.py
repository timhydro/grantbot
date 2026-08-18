from __future__ import annotations

from grantbot.discovery.engine import (
    DiscoveryEngine,
)

from grantbot.discovery.pages import (
    list_pages,
)

from grantbot.funding.planner import (
    build_discovery_plan,
)


def run_discovery_plan(
    *,
    state: str = "Florida",
    counties: list[str] | None = None,
    cities: list[str] | None = None,
    lanes: list[str] | None = None,
    max_queries: int = 20,
    per_query_limit: int = 10,
    use_web: bool = False,
    save: bool = True,
) -> dict:

    engine = DiscoveryEngine()

    plan = build_discovery_plan(
        state=state,
        counties=counties,
        cities=cities,
        lanes=lanes,
        max_terms_per_lane=2,
    )

    summary = {
        "planned":
            len(plan),

        "executed":
            0,

        "saved":
            0,

        "duplicates":
            0,

        "errors":
            0,

        "skipped_no_connector":
            0,

        "runs":
            [],
    }

    seen_pairs = set()

    for row in plan:

        if (
            summary["executed"]
            >= max_queries
        ):
            break

        source_key = (
            row["source_key"]
        )

        pair = (
            source_key,
            row["query"],
        )

        if pair in seen_pairs:
            continue

        seen_pairs.add(
            pair
        )

        try:

            if (
                source_key
                == "federal_grants_gov"
            ):

                result = (
                    engine.grants_gov(
                        query=row[
                            "query"
                        ],
                        limit=(
                            per_query_limit
                        ),
                        detail_limit=min(
                            5,
                            per_query_limit,
                        ),
                        save=save,
                        lane=row[
                            "lane"
                        ],
                    )
                )

            else:

                pages = list_pages(
                    source_key
                )

                if pages:

                    result = (
                        engine.crawl_registered_pages(
                            source_key=source_key,
                            query=row[
                                "query"
                            ],
                            geography=row.get(
                                "geography"
                            ),
                            limit=(
                                per_query_limit
                            ),
                            save=save,
                            lane=row[
                                "lane"
                            ],
                        )
                    )

                elif (
                    use_web
                    and engine.brave.enabled
                ):

                    result = (
                        engine.broad_web_search(
                            plan_row=row,
                            count=min(
                                per_query_limit,
                                10,
                            ),
                            max_pages=min(
                                per_query_limit,
                                6,
                            ),
                            save=save,
                        )
                    )

                else:

                    summary[
                        "skipped_no_connector"
                    ] += 1

                    continue

            summary[
                "executed"
            ] += 1

            summary[
                "saved"
            ] += int(
                result.get(
                    "saved",
                    0,
                )
            )

            summary[
                "duplicates"
            ] += int(
                result.get(
                    "duplicates",
                    0,
                )
            )

            summary[
                "errors"
            ] += int(
                result.get(
                    "errors",
                    0,
                )
            )

            summary[
                "runs"
            ].append({
                "source_key":
                    source_key,

                "lane":
                    row[
                        "lane"
                    ],

                "query":
                    row[
                        "query"
                    ],

                "saved":
                    result.get(
                        "saved",
                        0,
                    ),

                "duplicates":
                    result.get(
                        "duplicates",
                        0,
                    ),
            })

        except Exception as exc:

            summary[
                "executed"
            ] += 1

            summary[
                "errors"
            ] += 1

            summary[
                "runs"
            ].append({
                "source_key":
                    source_key,

                "lane":
                    row[
                        "lane"
                    ],

                "query":
                    row[
                        "query"
                    ],

                "error":
                    str(exc),
            })

    return summary
