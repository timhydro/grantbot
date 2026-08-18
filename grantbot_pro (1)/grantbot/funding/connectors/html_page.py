from __future__ import annotations

from urllib.parse import (
    urljoin,
    urlparse,
)

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

from grantbot.discovery.http import (
    HttpClient,
)

from grantbot.discovery.robots import (
    can_fetch,
)

from grantbot.funding.adapters import (
    FundingSourceAdapter,
    SearchRequest,
    SearchResult,
)


class OfficialFundingPageAdapter(
    FundingSourceAdapter
):

    def __init__(
        self,
        *,
        source_key: str,
        pages: list[dict],
        client: HttpClient | None = None,
    ):

        self.source_key = (
            source_key
        )

        self.pages = (
            pages
        )

        self.client = (
            client
            or HttpClient()
        )

    def search(
        self,
        request: SearchRequest,
    ):

        seen = set()

        result_count = 0

        for page in self.pages:

            if (
                result_count
                >= request.limit
            ):
                break

            page_url = (
                page["url"]
            )

            if (
                page.get(
                    "respect_robots",
                    1,
                )
                and not can_fetch(
                    page_url,
                    self.client,
                    self.client.user_agent,
                )
            ):
                continue

            html = (
                self.client.get_text(
                    page_url
                )
            )

            soup = BeautifulSoup(
                html,
                "html.parser",
            )

            max_links = int(
                page.get(
                    "max_links",
                    100,
                )
            )

            for anchor in soup.find_all(
                "a",
                href=True,
                limit=max_links,
            ):

                if (
                    result_count
                    >= request.limit
                ):
                    break

                href = urljoin(
                    page_url,
                    anchor.get(
                        "href"
                    ),
                )

                parsed = urlparse(
                    href
                )

                if parsed.scheme not in {
                    "http",
                    "https",
                }:
                    continue

                title = normalize_text(
                    anchor.get_text(
                        " ",
                        strip=True,
                    )
                )

                if not title:
                    title = (
                        parsed.path
                        .rstrip("/")
                        .split("/")[-1]
                        .replace(
                            "-",
                            " ",
                        )
                        .replace(
                            "_",
                            " ",
                        )
                    )

                parent = (
                    anchor.parent
                )

                context = normalize_text(
                    parent.get_text(
                        " ",
                        strip=True,
                    )
                    if parent
                    else title
                )

                material = (
                    f"{title} "
                    f"{context} "
                    f"{href}"
                )

                score = funding_relevance(
                    material,
                    request.query,
                )

                if score < 4:
                    continue

                dedupe_key = (
                    href.lower()
                )

                if dedupe_key in seen:
                    continue

                seen.add(
                    dedupe_key
                )

                floor, ceiling = (
                    extract_award_range(
                        context
                    )
                )

                yield SearchResult(
                    external_id=None,

                    title=title,

                    description=(
                        context[:1000]
                        or None
                    ),

                    eligibility=(
                        extract_eligibility_snippet(
                            context
                        )
                    ),

                    funder=(
                        page.get(
                            "source_name"
                        )
                    ),

                    agency=(
                        page.get(
                            "source_name"
                        )
                    ),

                    geography=(
                        request.geography
                    ),

                    deadline=(
                        extract_deadline(
                            context
                        )
                    ),

                    award_floor=floor,

                    award_ceiling=ceiling,

                    source_url=href,

                    raw={
                        "discovery_method":
                            "official_page",

                        "listing_page":
                            page_url,

                        "relevance_score":
                            score,
                    },
                )

                result_count += 1
