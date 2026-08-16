from __future__ import annotations

import xml.etree.ElementTree as ET

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

from grantbot.funding.adapters import (
    FundingSourceAdapter,
    SearchRequest,
    SearchResult,
)


def _text(
    element,
    names,
):
    for name in names:

        child = element.find(
            name
        )

        if (
            child is not None
            and child.text
        ):
            return normalize_text(
                child.text
            )

    return ""


class RSSFundingAdapter(
    FundingSourceAdapter
):

    def __init__(
        self,
        *,
        source_key: str,
        pages: list[dict],
        client: HttpClient | None = None,
    ):

        self.source_key = source_key

        self.pages = pages

        self.client = (
            client
            or HttpClient()
        )

    def search(
        self,
        request: SearchRequest,
    ):

        yielded = 0

        for page in self.pages:

            if (
                yielded
                >= request.limit
            ):
                break

            xml_text = (
                self.client.get_text(
                    page["url"]
                )
            )

            root = ET.fromstring(
                xml_text
            )

            items = list(
                root.findall(
                    ".//item"
                )
            )

            if not items:
                items = list(
                    root.findall(
                        ".//{*}entry"
                    )
                )

            for item in items:

                if (
                    yielded
                    >= request.limit
                ):
                    break

                title = _text(
                    item,
                    (
                        "title",
                        "{*}title",
                    ),
                )

                description = _text(
                    item,
                    (
                        "description",
                        "summary",
                        "{*}summary",
                        "{*}content",
                    ),
                )

                link = _text(
                    item,
                    (
                        "link",
                        "{*}link",
                    ),
                )

                if not link:

                    link_node = (
                        item.find(
                            "{*}link"
                        )
                    )

                    if (
                        link_node
                        is not None
                    ):
                        link = (
                            link_node.attrib.get(
                                "href",
                                "",
                            )
                        )

                material = (
                    f"{title} "
                    f"{description}"
                )

                score = funding_relevance(
                    material,
                    request.query,
                )

                if score < 4:
                    continue

                floor, ceiling = (
                    extract_award_range(
                        description
                    )
                )

                yield SearchResult(
                    external_id=None,

                    title=(
                        title
                        or "Funding opportunity"
                    ),

                    description=(
                        description
                        or None
                    ),

                    eligibility=(
                        extract_eligibility_snippet(
                            description
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
                            description
                        )
                    ),

                    award_floor=floor,

                    award_ceiling=ceiling,

                    source_url=(
                        link
                        or page["url"]
                    ),

                    raw={
                        "discovery_method":
                            "rss",

                        "feed":
                            page["url"],

                        "relevance_score":
                            score,
                    },
                )

                yielded += 1
