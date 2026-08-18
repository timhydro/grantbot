from __future__ import annotations

from typing import Iterable

from grantbot.core.errors import (
    ExternalServiceError,
)

from grantbot.core.utils import (
    normalize_text,
)

from grantbot.discovery.http import (
    HttpClient,
)

from grantbot.funding.adapters import (
    FundingSourceAdapter,
    SearchRequest,
    SearchResult,
)


SEARCH_URL = (
    "https://api.grants.gov/"
    "v1/api/search2"
)

DETAIL_URL = (
    "https://api.grants.gov/"
    "v1/api/fetchOpportunity"
)


ATTRIBUTION = (
    "This product uses the Grants.gov API "
    "but is not endorsed or certified by "
    "the U.S. Department of Health and "
    "Human Services."
)


def _float_or_none(
    value,
):
    if value is None:
        return None

    text = (
        str(value)
        .replace(
            "$",
            "",
        )
        .replace(
            ",",
            "",
        )
        .strip()
    )

    if not text:
        return None

    try:
        return float(
            text
        )

    except ValueError:
        return None


class GrantsGovAdapter(
    FundingSourceAdapter
):

    source_key = (
        "federal_grants_gov"
    )

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        enrich_details: bool = True,
        detail_limit: int = 10,
    ):

        self.client = (
            client
            or HttpClient()
        )

        self.enrich_details = (
            enrich_details
        )

        self.detail_limit = max(
            0,
            int(
                detail_limit
            ),
        )

    def fetch_detail(
        self,
        opportunity_id: str | int,
    ) -> dict:

        payload = {
            "opportunityId":
                int(
                    opportunity_id
                )
        }

        result = (
            self.client.post_json(
                DETAIL_URL,
                json_body=payload,
            )
        )

        if int(
            result.get(
                "errorcode",
                0,
            )
        ) != 0:
            raise ExternalServiceError(
                "Grants.gov fetchOpportunity "
                f"failed: {result.get('msg')}"
            )

        return (
            result.get(
                "data"
            )
            or {}
        )

    def search(
        self,
        request: SearchRequest,
    ) -> Iterable[SearchResult]:

        filters = dict(
            request.filters
            or {}
        )

        rows = min(
            max(
                int(
                    request.limit
                ),
                1,
            ),
            100,
        )

        payload = {
            "rows":
                rows,

            "keyword":
                request.query,

            "oppStatuses":
                filters.pop(
                    "oppStatuses",
                    (
                        "forecasted|posted"
                    ),
                ),
        }

        allowed = {
            "oppNum",
            "eligibilities",
            "agencies",
            "aln",
            "fundingCategories",
            "fundingInstruments",
            "startRecordNum",
            "sortBy",
        }

        for key, value in (
            filters.items()
        ):
            if (
                key in allowed
                and value not in (
                    None,
                    "",
                )
            ):
                payload[key] = (
                    value
                )

        result = (
            self.client.post_json(
                SEARCH_URL,
                json_body=payload,
            )
        )

        if int(
            result.get(
                "errorcode",
                0,
            )
        ) != 0:
            raise ExternalServiceError(
                "Grants.gov search2 failed: "
                f"{result.get('msg')}"
            )

        data = (
            result.get(
                "data"
            )
            or {}
        )

        hits = (
            data.get(
                "oppHits"
            )
            or []
        )

        for index, hit in enumerate(
            hits[:rows]
        ):

            opportunity_id = (
                hit.get(
                    "id"
                )
            )

            detail = {}

            if (
                self.enrich_details
                and opportunity_id
                and index
                < self.detail_limit
            ):
                try:
                    detail = (
                        self.fetch_detail(
                            opportunity_id
                        )
                    )
                except Exception:
                    detail = {}

            synopsis = (
                detail.get(
                    "synopsis"
                )
                or {}
            )

            applicant_types = (
                synopsis.get(
                    "applicantTypes"
                )
                or []
            )

            eligibility = "; ".join(
                normalize_text(
                    row.get(
                        "description"
                    )
                )
                for row
                in applicant_types
                if row.get(
                    "description"
                )
            )

            description = (
                synopsis.get(
                    "synopsisDesc"
                )
                or ""
            )

            agency_name = (
                hit.get(
                    "agencyName"
                )
                or synopsis.get(
                    "agencyName"
                )
                or (
                    detail.get(
                        "agencyDetails"
                    )
                    or {}
                ).get(
                    "agencyName"
                )
            )

            raw = {
                "search_hit":
                    hit,

                "detail":
                    detail,

                "grants_gov_attribution":
                    ATTRIBUTION,
            }

            yield SearchResult(
                external_id=(
                    str(
                        opportunity_id
                    )
                    if opportunity_id
                    is not None
                    else hit.get(
                        "number"
                    )
                ),

                title=(
                    hit.get(
                        "title"
                    )
                    or detail.get(
                        "opportunityTitle"
                    )
                    or "Untitled federal opportunity"
                ),

                description=(
                    normalize_text(
                        description
                    )
                    or None
                ),

                eligibility=(
                    eligibility
                    or None
                ),

                funder=(
                    agency_name
                ),

                agency=(
                    agency_name
                ),

                geography=(
                    "United States"
                ),

                deadline=(
                    hit.get(
                        "closeDate"
                    )
                    or detail.get(
                        "originalDueDateDesc"
                    )
                    or None
                ),

                award_floor=(
                    _float_or_none(
                        synopsis.get(
                            "awardFloor"
                        )
                    )
                ),

                award_ceiling=(
                    _float_or_none(
                        synopsis.get(
                            "awardCeiling"
                        )
                    )
                ),

                source_url=(
                    "https://www.grants.gov/"
                    "search-results-detail/"
                    f"{opportunity_id}"
                    if opportunity_id
                    else "https://www.grants.gov"
                ),

                raw=raw,
            )
