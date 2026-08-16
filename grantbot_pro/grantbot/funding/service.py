from __future__ import annotations

from grantbot.funding.planner import (
    build_discovery_plan,
)
from grantbot.funding.precheck import (
    precheck_source,
)
from grantbot.funding.registry import (
    list_sources,
    registry_stats,
)


def funding_intelligence_summary() -> dict:

    sources = list_sources()

    direct = []
    conditional = []
    investor_related = []

    for source in sources:

        check = precheck_source(
            source
        )

        record = {
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
                source[
                    "jurisdiction_level"
                ],

            "fit":
                source[
                    "nonprofit_fit"
                ],

            "precheck":
                check,
        }

        if (
            source[
                "source_kind"
            ]
            in {
                "ANGEL_NETWORK",
                "ANGEL_INVESTOR",
                "IMPACT_INVESTOR",
                "IMPACT_FUND",
                "PHILANTHROPIC_INVESTOR",
            }
        ):
            investor_related.append(
                record
            )

        elif source[
            "nonprofit_fit"
        ] == "DIRECT":
            direct.append(
                record
            )

        else:
            conditional.append(
                record
            )

    return {
        "registry":
            registry_stats(),

        "direct_nonprofit_sources":
            direct,

        "conditional_sources":
            conditional,

        "investor_sources":
            investor_related,
    }


def default_plan(
    *,
    counties: list[str] | None = None,
    cities: list[str] | None = None,
):
    return build_discovery_plan(
        state="Florida",
        counties=counties,
        cities=cities,
    )
