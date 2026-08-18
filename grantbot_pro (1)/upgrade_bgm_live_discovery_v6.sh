#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/grantbot_pro"
cd "$ROOT"

if [[ ! -f grantbot/app.py ]]; then
    echo "ERROR: grantbot/app.py not found." >&2
    exit 1
fi

if [[ ! -f grantbot/automation/opportunity_pipeline.py ]]; then
    echo "ERROR: v5 opportunity pipeline is not installed." >&2
    exit 1
fi

if [[ ! -d .venv ]]; then
    echo "ERROR: $ROOT/.venv not found." >&2
    exit 1
fi

source .venv/bin/activate

STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p backups grantbot/discovery grantbot/api tests logs

for target in \
    grantbot/discovery/grants_gov.py \
    grantbot/api/discovery_v6.py
do
    if [[ -f "$target" ]]; then
        cp "$target" "backups/$(basename "$target").${STAMP}.bak"
    fi
done

cp grantbot/app.py "backups/app_before_discovery_v6_${STAMP}.py"

touch grantbot/discovery/__init__.py
touch grantbot/api/__init__.py

cat > grantbot/discovery/grants_gov.py <<'PY'
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
PY

cat > grantbot/api/discovery_v6.py <<'PY'
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.discovery.grants_gov import (
    DEFAULT_KEYWORDS,
    discover,
)


router = APIRouter(
    prefix="/v6/discovery",
    tags=["GrantBot Live Funding Discovery v6"],
)


class DiscoveryRequest(BaseModel):
    keywords: list[str] = Field(
        default_factory=lambda: list(DEFAULT_KEYWORDS),
        min_length=1,
        max_length=25,
    )
    rows_per_keyword: int = Field(
        default=20,
        ge=1,
        le=100,
    )
    fetch_details: bool = True
    generate_drafts: bool = False


@router.get("/defaults")
def defaults() -> dict[str, Any]:
    return {
        "keywords": list(DEFAULT_KEYWORDS),
        "source": "Grants.gov",
        "statuses": [
            "posted",
            "forecasted",
        ],
    }


@router.post("/search")
def search(
    payload: DiscoveryRequest,
) -> dict[str, Any]:
    try:
        return discover(
            keywords=payload.keywords,
            rows_per_keyword=payload.rows_per_keyword,
            fetch_details=payload.fetch_details,
            generate_drafts=payload.generate_drafts,
        ).to_dict()

    except (
        RuntimeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc
PY

cat > tests/test_discovery_v6.py <<'PY'
from __future__ import annotations

import unittest
from unittest.mock import patch

from grantbot.discovery.grants_gov import (
    fetch_opportunity,
    normalize_opportunity,
    search_keyword,
)


SEARCH_RESPONSE = {
    "errorcode": 0,
    "msg": "Webservice Succeeds",
    "data": {
        "oppHits": [
            {
                "id": "12345",
                "number": "ABC-123",
                "title": "Reentry Workforce Program",
                "agencyCode": "HHS",
                "agencyName": "Health & Human Services",
                "openDate": "08/01/2026",
                "closeDate": "12/01/2099",
                "oppStatus": "posted",
            }
        ]
    },
}

DETAIL_RESPONSE = {
    "errorcode": 0,
    "msg": "Webservice Succeeds",
    "data": {
        "id": 12345,
        "opportunityNumber": "ABC-123",
        "opportunityTitle": "Reentry Workforce Program",
        "synopsis": {
            "agencyName": "Health & Human Services",
            "synopsisDesc": (
                "Supports reentry, homelessness, housing, "
                "employment and workforce development."
            ),
            "responseDateDesc": "12/01/2099",
            "awardCeiling": "500000",
            "awardFloor": "100000",
            "costSharing": False,
            "applicantTypes": [
                {
                    "id": "12",
                    "description": "Nonprofits having a 501(c)(3) status",
                }
            ],
        },
    },
}


class DiscoveryV6Tests(unittest.TestCase):
    @patch(
        "grantbot.discovery.grants_gov._post_json",
        return_value=SEARCH_RESPONSE,
    )
    def test_search_keyword(self, mock_post) -> None:
        hits = search_keyword(
            "reentry",
            rows=10,
        )

        self.assertEqual(
            len(hits),
            1,
        )

        self.assertEqual(
            hits[0]["id"],
            "12345",
        )

        mock_post.assert_called_once()

    @patch(
        "grantbot.discovery.grants_gov._post_json",
        return_value=DETAIL_RESPONSE,
    )
    def test_fetch_opportunity(self, mock_post) -> None:
        detail = fetch_opportunity(
            "12345"
        )

        self.assertEqual(
            detail["opportunityNumber"],
            "ABC-123",
        )

        mock_post.assert_called_once()

    def test_normalize(self) -> None:
        hit = SEARCH_RESPONSE[
            "data"
        ]["oppHits"][0]

        detail = DETAIL_RESPONSE[
            "data"
        ]

        opportunity = normalize_opportunity(
            hit,
            detail,
        )

        self.assertEqual(
            opportunity.id,
            "12345",
        )

        self.assertEqual(
            opportunity.amount,
            500000.0,
        )

        self.assertIn(
            "501(c)(3)",
            opportunity.eligibility,
        )

    def test_invalid_rows(self) -> None:
        with self.assertRaises(
            ValueError
        ):
            search_keyword(
                "reentry",
                rows=0,
            )


if __name__ == "__main__":
    unittest.main()
PY

python3 - <<'PY'
from pathlib import Path

p = Path("grantbot/app.py")
text = p.read_text(
    encoding="utf-8"
)

imp = (
    "from grantbot.api.discovery_v6 "
    "import router as discovery_v6_router"
)

reg = "app.include_router(discovery_v6_router)"

if imp not in text:
    text += "\n" + imp + "\n"

if reg not in text:
    text += reg + "\n"

p.write_text(
    text,
    encoding="utf-8",
)

print(
    "REGISTERED: /v6/discovery"
)
PY

python3 -m py_compile \
    grantbot/discovery/grants_gov.py \
    grantbot/api/discovery_v6.py \
    tests/test_discovery_v6.py

python3 -m unittest \
    tests.test_discovery_v6 \
    tests.test_master_v3_v5 \
    -v

python3 -m compileall -q grantbot

python3 -c \
"import grantbot.app; print('GRANTBOT APP IMPORT: OK')"

echo
echo "LIVE DISCOVERY V6 INSTALL COMPLETE"
echo "GET  /v6/discovery/defaults"
echo "POST /v6/discovery/search"
