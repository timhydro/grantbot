from __future__ import annotations

import hashlib
import json

from urllib.parse import urlparse

from grantbot.core.database import (
    connection,
    utc_now,
)

from grantbot.core.logging_config import (
    get_logger,
)

from grantbot.discovery.brave import (
    BraveSearchProvider,
)

from grantbot.discovery.dedupe import (
    fingerprint,
    fingerprint_exists,
    store_fingerprint,
)

from grantbot.discovery.http import (
    HttpClient,
)

from grantbot.discovery.page_analyzer import (
    analyze_live_page,
)

from grantbot.discovery.pages import (
    list_pages,
)

from grantbot.discovery.query_builder import (
    build_web_query,
)

from grantbot.discovery.runs import (
    event,
    finish_run,
    start_run,
)

from grantbot.funding.adapters import (
    SearchRequest,
)

from grantbot.funding.connectors.grants_gov import (
    GrantsGovAdapter,
)

from grantbot.funding.connectors.html_page import (
    OfficialFundingPageAdapter,
)

from grantbot.funding.connectors.rss import (
    RSSFundingAdapter,
)

from grantbot.funding.ingest import (
    ingest_opportunity,
)

from grantbot.funding.registry import (
    get_source,
)


logger = get_logger(
    "discovery.engine"
)


class DiscoveryEngine:

    def __init__(
        self,
        *,
        client: HttpClient | None = None,
    ):

        self.client = (
            client
            or HttpClient()
        )

        self.brave = (
            BraveSearchProvider(
                client=self.client
            )
        )

    @staticmethod
    def _synthetic_external_id(
        source_key: str,
        result,
    ) -> str:

        material = "|".join([
            source_key,
            str(
                result.source_url
                or ""
            ),
            str(
                result.title
                or ""
            ),
            str(
                result.deadline
                or ""
            ),
        ])

        return (
            "gb-"
            + hashlib.sha256(
                material.encode(
                    "utf-8"
                )
            ).hexdigest()[:24]
        )

    def save_result(
        self,
        *,
        source_key: str,
        result,
        lane: str | None = None,
    ) -> tuple[
        int | None,
        bool,
    ]:

        external_id = (
            result.external_id
            or self._synthetic_external_id(
                source_key,
                result,
            )
        )

        fp = fingerprint(
            source_key=source_key,
            title=result.title,
            source_url=result.source_url,
            external_id=external_id,
            deadline=result.deadline,
        )

        if fingerprint_exists(
            fp
        ):
            return (
                None,
                True,
            )

        raw = dict(
            result.raw
            or {}
        )

        if lane:
            raw[
                "grantbot_lane"
            ] = lane

        opportunity_id = (
            ingest_opportunity(
                source_key,
                {
                    "external_id":
                        external_id,

                    "opportunity_type":
                        (
                            "GRANT"
                            if source_key
                            != "angel_investors"
                            else "INVESTMENT"
                        ),

                    "title":
                        result.title,

                    "funder":
                        result.funder,

                    "agency":
                        result.agency,

                    "description":
                        result.description,

                    "eligibility":
                        result.eligibility,

                    "geography":
                        result.geography,

                    "deadline":
                        result.deadline,

                    "award_floor":
                        result.award_floor,

                    "award_ceiling":
                        result.award_ceiling,

                    "source_url":
                        result.source_url,

                    "status":
                        "DISCOVERED",

                    "raw":
                        raw,
                },
            )
        )

        store_fingerprint(
            opportunity_id,
            fp,
        )

        if lane:

            with connection() as conn:

                conn.execute(
                    """
                    INSERT OR IGNORE
                    INTO opportunity_tags(
                        opportunity_id,
                        tag
                    )
                    VALUES (?, ?)
                    """,
                    (
                        opportunity_id,
                        lane,
                    ),
                )

        return (
            opportunity_id,
            False,
        )

    def grants_gov(
        self,
        *,
        query: str,
        limit: int = 25,
        detail_limit: int = 10,
        save: bool = True,
        filters: dict | None = None,
        lane: str | None = None,
    ) -> dict:

        run_id = start_run(
            "GRANTS_GOV",
            {
                "query":
                    query,
            },
        )

        stats = {
            "run_id":
                run_id,

            "results":
                [],

            "seen":
                0,

            "saved":
                0,

            "duplicates":
                0,

            "errors":
                0,
        }

        adapter = GrantsGovAdapter(
            self.client,
            enrich_details=True,
            detail_limit=detail_limit,
        )

        try:

            request = SearchRequest(
                query=query,
                geography=(
                    "United States"
                ),
                limit=limit,
                filters=filters,
            )

            for result in adapter.search(
                request
            ):

                stats["seen"] += 1

                record = {
                    "external_id":
                        result.external_id,

                    "title":
                        result.title,

                    "agency":
                        result.agency,

                    "deadline":
                        result.deadline,

                    "award_floor":
                        result.award_floor,

                    "award_ceiling":
                        result.award_ceiling,

                    "source_url":
                        result.source_url,
                }

                if save:

                    opportunity_id, duplicate = (
                        self.save_result(
                            source_key=(
                                "federal_grants_gov"
                            ),
                            result=result,
                            lane=lane,
                        )
                    )

                    record[
                        "opportunity_id"
                    ] = opportunity_id

                    record[
                        "duplicate"
                    ] = duplicate

                    if duplicate:
                        stats[
                            "duplicates"
                        ] += 1
                    else:
                        stats[
                            "saved"
                        ] += 1

                stats[
                    "results"
                ].append(
                    record
                )

        except Exception as exc:

            stats["errors"] += 1

            event(
                run_id,
                event_type="ERROR",
                source_key=(
                    "federal_grants_gov"
                ),
                query_text=query,
                message=str(exc),
            )

            raise

        finally:

            finish_run(
                run_id,
                sources_attempted=1,
                queries_attempted=1,
                results_seen=(
                    stats["seen"]
                ),
                opportunities_saved=(
                    stats["saved"]
                ),
                duplicates_skipped=(
                    stats["duplicates"]
                ),
                errors=(
                    stats["errors"]
                ),
            )

        return stats

    def crawl_registered_pages(
        self,
        *,
        source_key: str,
        query: str,
        geography: str | None = None,
        limit: int = 25,
        save: bool = True,
        lane: str | None = None,
    ) -> dict:

        pages = list_pages(
            source_key
        )

        html_pages = [
            page
            for page in pages
            if page[
                "page_type"
            ] == "HTML"
        ]

        rss_pages = [
            page
            for page in pages
            if page[
                "page_type"
            ] == "RSS"
        ]

        run_id = start_run(
            "REGISTERED_PAGES",
            {
                "source_key":
                    source_key,

                "query":
                    query,
            },
        )

        stats = {
            "run_id":
                run_id,

            "pages":
                len(pages),

            "seen":
                0,

            "saved":
                0,

            "duplicates":
                0,

            "errors":
                0,

            "results":
                [],
        }

        adapters = []

        if html_pages:
            adapters.append(
                OfficialFundingPageAdapter(
                    source_key=source_key,
                    pages=html_pages,
                    client=self.client,
                )
            )

        if rss_pages:
            adapters.append(
                RSSFundingAdapter(
                    source_key=source_key,
                    pages=rss_pages,
                    client=self.client,
                )
            )

        try:

            for adapter in adapters:

                request = SearchRequest(
                    query=query,
                    geography=geography,
                    limit=limit,
                )

                for result in adapter.search(
                    request
                ):

                    stats[
                        "seen"
                    ] += 1

                    if save:

                        opportunity_id, duplicate = (
                            self.save_result(
                                source_key=source_key,
                                result=result,
                                lane=lane,
                            )
                        )

                        if duplicate:
                            stats[
                                "duplicates"
                            ] += 1
                        else:
                            stats[
                                "saved"
                            ] += 1

                    else:

                        opportunity_id = (
                            None
                        )

                        duplicate = False

                    stats[
                        "results"
                    ].append({
                        "title":
                            result.title,

                        "source_url":
                            result.source_url,

                        "deadline":
                            result.deadline,

                        "opportunity_id":
                            opportunity_id,

                        "duplicate":
                            duplicate,
                    })

        except Exception as exc:

            stats[
                "errors"
            ] += 1

            event(
                run_id,
                event_type="ERROR",
                source_key=source_key,
                query_text=query,
                message=str(exc),
            )

            raise

        finally:

            finish_run(
                run_id,
                sources_attempted=(
                    len(
                        adapters
                    )
                ),
                queries_attempted=1,
                results_seen=(
                    stats[
                        "seen"
                    ]
                ),
                opportunities_saved=(
                    stats[
                        "saved"
                    ]
                ),
                duplicates_skipped=(
                    stats[
                        "duplicates"
                    ]
                ),
                errors=(
                    stats[
                        "errors"
                    ]
                ),
            )

        return stats

    def broad_web_search(
        self,
        *,
        plan_row: dict,
        count: int = 10,
        save: bool = True,
        max_pages: int = 6,
    ) -> dict:

        source_key = (
            plan_row[
                "source_key"
            ]
        )

        source = get_source(
            source_key
        )

        if not source:
            raise ValueError(
                f"Unknown source: "
                f"{source_key}"
            )

        web_query = (
            build_web_query(
                plan_row
            )
        )

        run_id = start_run(
            "WEB_SEARCH",
            {
                "query":
                    web_query,

                "source_key":
                    source_key,
            },
        )

        stats = {
            "run_id":
                run_id,

            "query":
                web_query,

            "candidates":
                0,

            "pages_analyzed":
                0,

            "seen":
                0,

            "saved":
                0,

            "duplicates":
                0,

            "errors":
                0,

            "results":
                [],
        }

        try:

            candidates = (
                self.brave.search(
                    web_query,
                    count=count,
                )
            )

            stats[
                "candidates"
            ] = len(
                candidates
            )

            for candidate in (
                candidates[
                    :max_pages
                ]
            ):

                url = (
                    candidate[
                        "url"
                    ]
                )

                try:

                    result = (
                        analyze_live_page(
                            url=url,
                            source_key=source_key,
                            source_name=source[
                                "source_name"
                            ],
                            query=(
                                plan_row[
                                    "query"
                                ]
                            ),
                            geography=(
                                plan_row.get(
                                    "geography"
                                )
                            ),
                            client=(
                                self.client
                            ),
                            search_title=(
                                candidate.get(
                                    "title"
                                )
                            ),
                        )
                    )

                    stats[
                        "pages_analyzed"
                    ] += 1

                except Exception as exc:

                    event(
                        run_id,
                        event_type=(
                            "PAGE_ERROR"
                        ),
                        source_key=(
                            source_key
                        ),
                        query_text=(
                            web_query
                        ),
                        message=(
                            f"{url}: {exc}"
                        ),
                    )

                    stats[
                        "errors"
                    ] += 1

                    continue

                if result is None:
                    continue

                stats[
                    "seen"
                ] += 1

                opportunity_id = None
                duplicate = False

                if save:

                    opportunity_id, duplicate = (
                        self.save_result(
                            source_key=(
                                source_key
                            ),
                            result=result,
                            lane=(
                                plan_row.get(
                                    "lane"
                                )
                            ),
                        )
                    )

                    if duplicate:

                        stats[
                            "duplicates"
                        ] += 1

                    else:

                        stats[
                            "saved"
                        ] += 1

                stats[
                    "results"
                ].append({
                    "title":
                        result.title,

                    "source_url":
                        result.source_url,

                    "deadline":
                        result.deadline,

                    "opportunity_id":
                        opportunity_id,

                    "duplicate":
                        duplicate,
                })

        except Exception as exc:

            stats[
                "errors"
            ] += 1

            event(
                run_id,
                event_type="ERROR",
                source_key=source_key,
                query_text=web_query,
                message=str(exc),
            )

            raise

        finally:

            finish_run(
                run_id,
                sources_attempted=1,
                queries_attempted=1,
                results_seen=(
                    stats[
                        "seen"
                    ]
                ),
                opportunities_saved=(
                    stats[
                        "saved"
                    ]
                ),
                duplicates_skipped=(
                    stats[
                        "duplicates"
                    ]
                ),
                errors=(
                    stats[
                        "errors"
                    ]
                ),
            )

        return stats
