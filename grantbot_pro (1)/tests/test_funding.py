from grantbot.core.database import (
    initialize_database,
)

from grantbot.funding.planner import (
    build_discovery_plan,
)

from grantbot.funding.precheck import (
    precheck_source,
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

from grantbot.investors.structure_guard import (
    analyze_source_structure,
)


def setup_module():
    initialize_database()
    initialize_funding_schema()
    seed_catalog()


def test_registry_has_broad_sources():
    sources = list_sources()

    assert len(
        sources
    ) >= 15


def test_federal_source_exists():
    source = get_source(
        "federal_grants_gov"
    )

    assert source is not None

    assert (
        source[
            "jurisdiction_level"
        ]
        == "FEDERAL"
    )


def test_county_source_exists():
    source = get_source(
        "florida_counties"
    )

    assert source is not None

    assert (
        source[
            "jurisdiction_level"
        ]
        == "COUNTY"
    )


def test_city_source_exists():
    source = get_source(
        "florida_cities"
    )

    assert source is not None

    assert (
        source[
            "jurisdiction_level"
        ]
        == "CITY"
    )


def test_angel_source_guard():
    source = get_source(
        "angel_investors"
    )

    result = (
        analyze_source_structure(
            source
        )
    )

    assert (
        result[
            "requires_investable_entity"
        ]
        is True
    )

    assert (
        result[
            "requires_legal_review"
        ]
        is True
    )


def test_nonprofit_precheck():
    source = get_source(
        "community_foundations"
    )

    result = precheck_source(
        source
    )

    assert (
        result[
            "direct_fit"
        ]
        is True
    )

    assert (
        result[
            "score"
        ]
        == 100
    )


def test_discovery_plan():
    plan = build_discovery_plan(
        state="Florida",
        counties=[
            "Sarasota"
        ],
        cities=[
            "Venice"
        ],
        max_terms_per_lane=1,
    )

    assert len(plan) > 20

    queries = [
        row["query"].lower()
        for row in plan
    ]

    assert any(
        "sarasota county"
        in query
        for query in queries
    )

    assert any(
        "venice"
        in query
        for query in queries
    )


def test_registry_stats():
    stats = registry_stats()

    assert (
        stats[
            "total_sources"
        ]
        >= 15
    )

    assert (
        "FEDERAL"
        in stats[
            "by_jurisdiction"
        ]
    )

    assert (
        "COUNTY"
        in stats[
            "by_jurisdiction"
        ]
    )

    assert (
        "CITY"
        in stats[
            "by_jurisdiction"
        ]
    )
