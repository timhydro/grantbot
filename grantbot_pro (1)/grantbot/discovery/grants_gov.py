from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from grantbot.automation.opportunity_pipeline import (
    Opportunity,
    rank_opportunities,
)


SEARCH_URL = "https://api.grants.gov/v1/api/search2"
FETCH_URL = "https://api.grants.gov/v1/api/fetchOpportunity"

DEFAULT_KEYWORDS = [
    "reentry",
    "formerly incarcerated",
    "homelessness",
    "supportive housing",
    "transitional housing",
    "workforce development",
    "employment training",
    "community development",
    "economic opportunity",
]


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    keywords: list[str]
    raw_hits: int
    unique_hits: int
    results: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _post_json(
    url: str,
    body: dict[str, Any],
    *,
    timeout: int = 45,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "BrokenGrowthMinistries-GrantBot/6.0",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode(
            "utf-8",
            errors="replace",
        )
        raise RuntimeError(
            f"Grants.gov HTTP {exc.code}: {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Could not reach Grants.gov: {exc.reason}"
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Grants.gov returned invalid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Grants.gov response root was not an object."
        )

    if payload.get("errorcode") not in (None, 0):
        raise RuntimeError(
            f"Grants.gov API error: {payload.get('msg', 'unknown error')}"
        )

    return payload


def search_keyword(
    keyword: str,
    *,
    rows: int = 25,
    start_record_num: int = 0,
    statuses: str = "posted|forecasted",
) -> list[dict[str, Any]]:
    keyword = keyword.strip()

    if not keyword:
        raise ValueError("keyword cannot be empty")

    if rows < 1 or rows > 100:
        raise ValueError("rows must be between 1 and 100")

    if start_record_num < 0:
        raise ValueError("start_record_num cannot be negative")

    payload = _post_json(
        SEARCH_URL,
        {
            "rows": rows,
            "keyword": keyword,
            "oppStatuses": statuses,
            "startRecordNum": start_record_num,
        },
    )

    data = payload.get("data") or {}

    hits = data.get("oppHits") or []

    if not isinstance(hits, list):
        return []

    return [
        hit
        for hit in hits
        if isinstance(hit, dict)
    ]


def fetch_opportunity(
    opportunity_id: str | int,
) -> dict[str, Any]:
    try:
        oid = int(str(opportunity_id))
    except ValueError as exc:
        raise ValueError(
            "opportunity_id must be numeric"
        ) from exc

    payload = _post_json(
        FETCH_URL,
        {
            "opportunityId": oid,
        },
    )

    data = payload.get("data")

    if not isinstance(data, dict):
        raise RuntimeError(
            f"No detail data returned for opportunity {oid}."
        )

    return data


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(
            str(value)
            .replace("$", "")
            .replace(",", "")
            .strip()
        )
    except ValueError:
        return None


def _applicant_types(
    detail: dict[str, Any],
) -> str:
    synopsis = detail.get("synopsis") or {}

    applicant_types = synopsis.get("applicantTypes") or []

    values = []

    for item in applicant_types:
        if not isinstance(item, dict):
            continue

        description = str(
            item.get("description", "")
        ).strip()

        if description and description not in values:
            values.append(description)

    return "; ".join(values)


def _description(
    detail: dict[str, Any],
) -> str:
    synopsis = detail.get("synopsis") or {}

    fields = [
        synopsis.get("synopsisDesc"),
        synopsis.get("agencyContactDesc"),
        detail.get("originalDueDateDesc"),
    ]

    return "\n".join(
        str(value).strip()
        for value in fields
        if value not in (None, "")
    )


def _funder(
    detail: dict[str, Any],
    hit: dict[str, Any],
) -> str:
    synopsis = detail.get("synopsis") or {}

    candidates = [
        synopsis.get("agencyName"),
        (detail.get("agencyDetails") or {}).get("agencyName"),
        hit.get("agencyName"),
        hit.get("agencyCode"),
    ]

    for value in candidates:
        text = str(value or "").strip()

        if text:
            return text

    return ""


def normalize_opportunity(
    hit: dict[str, Any],
    detail: dict[str, Any] | None = None,
) -> Opportunity:
    detail = detail or {}

    oid = str(
        hit.get("id")
        or detail.get("id")
        or ""
    ).strip()

    if not oid:
        raise ValueError(
            "Grants.gov opportunity id is missing"
        )

    title = str(
        detail.get("opportunityTitle")
        or hit.get("title")
        or ""
    ).strip()

    if not title:
        raise ValueError(
            f"Opportunity {oid} has no title"
        )

    synopsis = detail.get("synopsis") or {}

    description = _description(detail)

    eligibility = _applicant_types(detail)

    close_date = str(
        hit.get("closeDate")
        or synopsis.get("responseDateDesc")
        or ""
    ).strip() or None

    amount = _float_or_none(
        synopsis.get("awardCeiling")
    )

    number = str(
        detail.get("opportunityNumber")
        or hit.get("number")
        or oid
    ).strip()

    nofo_text_parts = [
        title,
        number,
        _funder(detail, hit),
        description,
        eligibility,
    ]

    nofo_text = "\n".join(
        value
        for value in nofo_text_parts
        if value
    )

    return Opportunity(
        id=oid,
        title=title,
        funder=_funder(detail, hit),
        description=description,
        eligibility=eligibility,
        deadline=close_date,
        amount=amount,
        source_url=(
            "https://www.grants.gov/search-results-detail/"
            + oid
        ),
        nofo_text=nofo_text,
        metadata={
            "opportunity_number": number,
            "status": hit.get("oppStatus"),
            "open_date": hit.get("openDate"),
            "agency_code": hit.get("agencyCode"),
            "award_floor": _float_or_none(
                synopsis.get("awardFloor")
            ),
            "cost_sharing": synopsis.get("costSharing"),
        },
    )


def discover(
    *,
    keywords: list[str] | None = None,
    rows_per_keyword: int = 20,
    fetch_details: bool = True,
    generate_drafts: bool = False,
) -> DiscoveryResult:
    keywords = [
        keyword.strip()
        for keyword in (keywords or DEFAULT_KEYWORDS)
        if keyword.strip()
    ]

    if not keywords:
        raise ValueError(
            "At least one discovery keyword is required."
        )

    if len(keywords) > 25:
        raise ValueError(
            "A maximum of 25 keywords is allowed per discovery run."
        )

    hits: list[dict[str, Any]] = []

    for keyword in keywords:
        hits.extend(
            search_keyword(
                keyword,
                rows=rows_per_keyword,
            )
        )

    unique_hits: dict[str, dict[str, Any]] = {}

    for hit in hits:
        oid = str(hit.get("id", "")).strip()

        if oid:
            unique_hits.setdefault(
                oid,
                hit,
            )

    opportunities: list[Opportunity] = []

    for oid, hit in unique_hits.items():
        detail = (
            fetch_opportunity(oid)
            if fetch_details
            else {}
        )

        opportunities.append(
            normalize_opportunity(
                hit,
                detail,
            )
        )

    ranked = rank_opportunities(
        opportunities,
        generate_drafts=generate_drafts,
    )

    return DiscoveryResult(
        keywords=keywords,
        raw_hits=len(hits),
        unique_hits=len(unique_hits),
        results=ranked,
    )
