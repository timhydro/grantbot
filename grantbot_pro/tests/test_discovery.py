from grantbot.core.database import (
    initialize_database,
)

from grantbot.discovery.dedupe import (
    fingerprint,
)

from grantbot.discovery.extract import (
    extract_award_range,
    extract_deadline,
    funding_relevance,
)

from grantbot.discovery.pages import (
    add_page,
    list_pages,
)

from grantbot.discovery.query_builder import (
    build_web_query,
)

from grantbot.discovery.schema import (
    initialize_discovery_schema,
)

from grantbot.funding.connectors.grants_gov import (
    ATTRIBUTION,
    GrantsGovAdapter,
)

from grantbot.funding.adapters import (
    SearchRequest,
)

from grantbot.funding.registry import (
    seed_catalog,
)

from grantbot.funding.schema import (
    initialize_funding_schema,
)


class FakeClient:

    user_agent = (
        "GrantBotPro-Test"
    )

    def post_json(
        self,
        url,
        *,
        json_body,
        **kwargs,
    ):

        if url.endswith(
            "/search2"
        ):

            return {
                "errorcode": 0,

                "msg":
                    "Webservice Succeeds",

                "data": {
                    "hitCount": 1,

                    "oppHits": [{
                        "id":
                            "289999",

                        "number":
                            "TEST-001",

                        "title":
                            "Reentry Workforce Housing Grant",

                        "agencyCode":
                            "TEST",

                        "agencyName":
                            "Test Agency",

                        "openDate":
                            "01/01/2026",

                        "closeDate":
                            "12/31/2026",

                        "oppStatus":
                            "posted",

                        "alnist":
                            [
                                "00.000"
                            ],
                    }],
                },
            }

        if url.endswith(
            "/fetchOpportunity"
        ):

            return {
                "errorcode": 0,

                "data": {
                    "id":
                        289999,

                    "opportunityTitle":
                        "Reentry Workforce Housing Grant",

                    "synopsis": {
                        "agencyName":
                            "Test Agency",

                        "synopsisDesc":
                            (
                                "Funds workforce, "
                                "housing, and reentry."
                            ),

                        "awardFloor":
                            "50000",

                        "awardCeiling":
                            "250000",

                        "applicantTypes": [{
                            "id":
                                "12",

                            "description":
                                (
                                    "Nonprofits having "
                                    "a 501(c)(3) status"
                                ),
                        }],
                    },
                },
            }

        raise AssertionError(
            f"Unexpected URL: {url}"
        )


def setup_module():

    initialize_database()

    initialize_funding_schema()

    initialize_discovery_schema()

    seed_catalog()


def test_grants_gov_normalization():

    adapter = GrantsGovAdapter(
        client=FakeClient(),
        enrich_details=True,
        detail_limit=1,
    )

    results = list(
        adapter.search(
            SearchRequest(
                query="reentry",
                limit=5,
            )
        )
    )

    assert len(
        results
    ) == 1

    result = results[0]

    assert (
        result.external_id
        == "289999"
    )

    assert (
        result.award_floor
        == 50000
    )

    assert (
        result.award_ceiling
        == 250000
    )

    assert (
        "501(c)(3)"
        in result.eligibility
    )


def test_grants_gov_attribution():

    assert (
        "not endorsed"
        in ATTRIBUTION
    )


def test_relevance():

    score = funding_relevance(
        (
            "Notice of Funding Opportunity "
            "for nonprofit reentry housing "
            "and workforce development"
        ),
        "reentry housing",
    )

    assert score >= 10


def test_deadline():

    deadline = extract_deadline(
        (
            "Applications are accepted now. "
            "Application deadline: "
            "December 15, 2026."
        )
    )

    assert (
        deadline
        == "December 15, 2026"
    )


def test_award_range():

    low, high = (
        extract_award_range(
            (
                "Awards range from "
                "$25,000 to $100,000."
            )
        )
    )

    assert low == 25000

    assert high == 100000


def test_fingerprint_stable():

    one = fingerprint(
        source_key="test",
        title="Grant A",
        source_url=(
            "https://example.org/a"
        ),
    )

    two = fingerprint(
        source_key="test",
        title="Grant A",
        source_url=(
            "https://example.org/a"
        ),
    )

    assert one == two


def test_page_registration():

    page = add_page(
        source_key=(
            "community_foundations"
        ),
        url=(
            "https://example.org/"
            "funding-opportunities"
        ),
        page_name=(
            "Test Funding Page"
        ),
        page_type="HTML",
    )

    assert (
        page["source_key"]
        == "community_foundations"
    )

    pages = list_pages(
        "community_foundations"
    )

    assert any(
        row["url"]
        == (
            "https://example.org/"
            "funding-opportunities"
        )
        for row in pages
    )


def test_government_web_query():

    query = build_web_query({
        "query":
            "reentry Sarasota County Florida",

        "lane":
            "reentry",

        "source_kind":
            "GOVERNMENT",

        "jurisdiction":
            "COUNTY",
    })

    assert (
        "site:.gov"
        in query
    )

    assert (
        "reentry"
        in query
    )
