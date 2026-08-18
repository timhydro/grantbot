from __future__ import annotations

import argparse
import json

from grantbot.core.database import (
    initialize_database,
)

from grantbot.funding.planner import (
    build_discovery_plan,
    save_plan,
)

from grantbot.funding.registry import (
    get_source,
    list_sources,
    registry_stats,
    seed_catalog,
)

from grantbot.funding.schema import (
    initialize_funding_schema,
)

from grantbot.funding.service import (
    funding_intelligence_summary,
)


def pretty(value):
    print(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )
    )


def parser():
    p = argparse.ArgumentParser(
        prog="grantbot-funding",
        description=(
            "GrantBot Pro universal funding "
            "and investor intelligence"
        ),
    )

    sub = p.add_subparsers(
        dest="command"
    )

    sub.add_parser(
        "seed",
        help="Seed universal funding registry.",
    )

    sub.add_parser(
        "sources",
        help="List funding sources.",
    )

    sub.add_parser(
        "stats",
        help="Show registry statistics.",
    )

    sub.add_parser(
        "summary",
        help="Show funding intelligence summary.",
    )

    show = sub.add_parser(
        "show",
        help="Show one funding source.",
    )

    show.add_argument(
        "source_key"
    )

    plan = sub.add_parser(
        "plan",
        help="Generate a discovery plan.",
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
        "--save",
        action="store_true",
    )

    return p


def main():
    initialize_database()
    initialize_funding_schema()

    p = parser()
    args = p.parse_args()

    if args.command == "seed":

        count = seed_catalog()

        print(
            f"Seeded {count} "
            f"universal funding sources."
        )

        return

    if args.command == "sources":

        pretty(
            list_sources()
        )

        return

    if args.command == "stats":

        pretty(
            registry_stats()
        )

        return

    if args.command == "summary":

        pretty(
            funding_intelligence_summary()
        )

        return

    if args.command == "show":

        source = get_source(
            args.source_key
        )

        if not source:
            raise SystemExit(
                "Funding source not found."
            )

        pretty(
            source
        )

        return

    if args.command == "plan":

        plan = build_discovery_plan(
            state=args.state,
            counties=args.county,
            cities=args.city,
            lanes=args.lane or None,
        )

        if args.save:
            saved = save_plan(
                plan
            )

            print(
                f"Saved {saved} "
                f"discovery queries."
            )

        pretty({
            "query_count":
                len(plan),

            "plan":
                plan,
        })

        return

    p.print_help()


if __name__ == "__main__":
    main()
