from __future__ import annotations

import argparse
import json

from grantbot.core.database import (
    initialize_database,
)

from grantbot.discovery.brave import (
    BraveSearchProvider,
)

from grantbot.discovery.cache import (
    FileCache,
)

from grantbot.discovery.engine import (
    DiscoveryEngine,
)

from grantbot.discovery.pages import (
    add_page,
    list_pages,
    remove_page,
)

from grantbot.discovery.runner import (
    run_discovery_plan,
)

from grantbot.discovery.schema import (
    initialize_discovery_schema,
)

from grantbot.discovery.stats import (
    discovery_stats,
)

from grantbot.funding.registry import (
    seed_catalog,
)

from grantbot.funding.schema import (
    initialize_funding_schema,
)


def pretty(value):

    print(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


def build_parser():

    parser = argparse.ArgumentParser(
        prog="grantbot-discovery",

        description=(
            "GrantBot Pro live funding "
            "discovery engine"
        ),
    )

    sub = parser.add_subparsers(
        dest="command"
    )

    grants = sub.add_parser(
        "grants-gov",
        help=(
            "Search live Grants.gov "
            "opportunities."
        ),
    )

    grants.add_argument(
        "query"
    )

    grants.add_argument(
        "--limit",
        type=int,
        default=20,
    )

    grants.add_argument(
        "--details",
        type=int,
        default=5,
    )

    grants.add_argument(
        "--no-save",
        action="store_true",
    )

    grants.add_argument(
        "--lane",
        default=None,
    )


    page = sub.add_parser(
        "add-page",
        help=(
            "Register an official funding "
            "page or RSS feed."
        ),
    )

    page.add_argument(
        "--source-key",
        required=True,
    )

    page.add_argument(
        "--url",
        required=True,
    )

    page.add_argument(
        "--name",
        default=None,
    )

    page.add_argument(
        "--type",
        default="HTML",
        choices=[
            "HTML",
            "RSS",
            "JSON",
        ],
    )

    page.add_argument(
        "--max-links",
        type=int,
        default=100,
    )

    page.add_argument(
        "--ignore-robots",
        action="store_true",
    )


    pages = sub.add_parser(
        "pages",
        help=(
            "List registered live "
            "funding pages."
        ),
    )

    pages.add_argument(
        "--source-key",
        default=None,
    )


    remove = sub.add_parser(
        "remove-page",
        help=(
            "Remove a registered page."
        ),
    )

    remove.add_argument(
        "page_id",
        type=int,
    )


    crawl = sub.add_parser(
        "crawl",
        help=(
            "Search registered official "
            "pages for a source."
        ),
    )

    crawl.add_argument(
        "--source-key",
        required=True,
    )

    crawl.add_argument(
        "--query",
        required=True,
    )

    crawl.add_argument(
        "--geography",
        default="Florida",
    )

    crawl.add_argument(
        "--limit",
        type=int,
        default=25,
    )

    crawl.add_argument(
        "--lane",
        default=None,
    )

    crawl.add_argument(
        "--no-save",
        action="store_true",
    )


    web = sub.add_parser(
        "web-search",
        help=(
            "Run an optional Brave "
            "Search discovery query."
        ),
    )

    web.add_argument(
        "query"
    )

    web.add_argument(
        "--count",
        type=int,
        default=10,
    )


    plan = sub.add_parser(
        "run-plan",
        help=(
            "Execute Module 03's universal "
            "funding discovery plan."
        ),
    )

    plan.add_argument(
        "--state",
        default="Florida",
    )

    plan.add_argument(
        "--county",
        action="append",
        default=[],
    )

    plan.add_argument(
        "--city",
        action="append",
        default=[],
    )

    plan.add_argument(
        "--lane",
        action="append",
        default=[],
    )

    plan.add_argument(
        "--max-queries",
        type=int,
        default=20,
    )

    plan.add_argument(
        "--per-query",
        type=int,
        default=10,
    )

    plan.add_argument(
        "--web",
        action="store_true",
    )

    plan.add_argument(
        "--no-save",
        action="store_true",
    )


    live = sub.add_parser(
        "live-test",
        help=(
            "Verify live Grants.gov "
            "connectivity."
        ),
    )

    live.add_argument(
        "--query",
        default="reentry",
    )


    sub.add_parser(
        "stats",
        help=(
            "Show discovery statistics."
        ),
    )


    sub.add_parser(
        "clear-cache",
        help=(
            "Clear HTTP discovery cache."
        ),
    )

    return parser


def initialize():

    initialize_database()

    initialize_funding_schema()

    initialize_discovery_schema()

    seed_catalog()


def main():

    initialize()

    parser = build_parser()

    args = parser.parse_args()

    if args.command == "grants-gov":

        engine = DiscoveryEngine()

        pretty(
            engine.grants_gov(
                query=args.query,
                limit=args.limit,
                detail_limit=args.details,
                save=(
                    not args.no_save
                ),
                lane=args.lane,
            )
        )

        return


    if args.command == "add-page":

        pretty(
            add_page(
                source_key=(
                    args.source_key
                ),
                url=args.url,
                page_name=args.name,
                page_type=args.type,
                respect_robots=(
                    not args.ignore_robots
                ),
                max_links=(
                    args.max_links
                ),
            )
        )

        return


    if args.command == "pages":

        pretty(
            list_pages(
                args.source_key
            )
        )

        return


    if args.command == "remove-page":

        print(
            "REMOVED"
            if remove_page(
                args.page_id
            )
            else "NOT FOUND"
        )

        return


    if args.command == "crawl":

        engine = DiscoveryEngine()

        pretty(
            engine.crawl_registered_pages(
                source_key=(
                    args.source_key
                ),
                query=args.query,
                geography=(
                    args.geography
                ),
                limit=args.limit,
                save=(
                    not args.no_save
                ),
                lane=args.lane,
            )
        )

        return


    if args.command == "web-search":

        provider = (
            BraveSearchProvider()
        )

        pretty(
            provider.search(
                args.query,
                count=args.count,
            )
        )

        return


    if args.command == "run-plan":

        pretty(
            run_discovery_plan(
                state=args.state,
                counties=args.county,
                cities=args.city,
                lanes=(
                    args.lane
                    or None
                ),
                max_queries=(
                    args.max_queries
                ),
                per_query_limit=(
                    args.per_query
                ),
                use_web=args.web,
                save=(
                    not args.no_save
                ),
            )
        )

        return


    if args.command == "live-test":

        engine = DiscoveryEngine()

        result = (
            engine.grants_gov(
                query=args.query,
                limit=3,
                detail_limit=1,
                save=False,
            )
        )

        print(
            "GRANTS.GOV LIVE: OK"
        )

        pretty({
            "results_seen":
                result[
                    "seen"
                ],

            "sample":
                result[
                    "results"
                ][:3],
        })

        return


    if args.command == "stats":

        pretty(
            discovery_stats()
        )

        return


    if args.command == "clear-cache":

        count = (
            FileCache().clear()
        )

        print(
            f"Cleared {count} "
            f"cached HTTP responses."
        )

        return


    parser.print_help()


if __name__ == "__main__":
    main()
