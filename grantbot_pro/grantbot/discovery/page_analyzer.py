from __future__ import annotations

from bs4 import BeautifulSoup

from grantbot.core.utils import (
    normalize_text,
)

from grantbot.discovery.extract import (
    extract_award_range,
    extract_deadline,
    extract_eligibility_snippet,
    funding_relevance,
)

from grantbot.discovery.robots import (
    can_fetch,
)

from grantbot.funding.adapters import (
    SearchResult,
)


def analyze_live_page(
    *,
    url: str,
    source_key: str,
    source_name: str,
    query: str,
    geography: str | None,
    client,
    search_title: str | None = None,
    respect_robots: bool = True,
) -> SearchResult | None:

    if (
        respect_robots
        and not can_fetch(
            url,
            client,
            client.user_agent,
        )
    ):
        return None

    response = client.request(
        "GET",
        url,
    )

    content_type = (
        response.headers.get(
            "Content-Type",
            ""
        ).lower()
    )

    if (
        "text/html"
        not in content_type
        and "<html"
        not in response.text[
            :500
        ].lower()
    ):
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg",
    ]):
        tag.decompose()

    title = ""

    if soup.title:
        title = normalize_text(
            soup.title.get_text(
                " ",
                strip=True,
            )
        )

    if not title:
        title = (
            search_title
            or "Funding opportunity"
        )

    text = normalize_text(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    if len(text) > 150000:
        text = text[:150000]

    relevance = funding_relevance(
        (
            f"{title} "
            f"{text}"
        ),
        query,
    )

    if relevance < 8:
        return None

    floor, ceiling = (
        extract_award_range(
            text
        )
    )

    return SearchResult(
        external_id=None,

        title=title[:500],

        description=(
            text[:1800]
            or None
        ),

        eligibility=(
            extract_eligibility_snippet(
                text
            )
        ),

        funder=source_name,

        agency=source_name,

        geography=geography,

        deadline=(
            extract_deadline(
                text
            )
        ),

        award_floor=floor,

        award_ceiling=ceiling,

        source_url=url,

        raw={
            "discovery_method":
                "web_page_analysis",

            "source_key":
                source_key,

            "relevance_score":
                relevance,

            "content_type":
                content_type,
        },
    )
