from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from grantbot.automation.opportunity_pipeline import Opportunity, analyze_opportunity
from grantbot.automation.review_router import create_review_folder_from_analysis
from grantbot.eligibility.tax_status import TaxStatus
from grantbot.funding.adapters import SearchRequest, SearchResult
from grantbot.funding.connectors.grants_gov import GrantsGovAdapter
from grantbot.funding.connectors.html_page import OfficialFundingPageAdapter
from grantbot.funding.ingest import ingest_opportunity
from grantbot.funding.planner import build_discovery_plan
from grantbot.funding.registry import seed_catalog


OFFICIAL_SOURCE_PAGES: dict[str, list[dict[str, Any]]] = {
    "kiva_us": [
        {"url": "https://www.kiva.org/borrow", "source_name": "Kiva U.S.", "max_links": 120},
    ],
    "florida_community_loan_fund": [
        {"url": "https://www.fclf.org/", "source_name": "Florida Community Loan Fund", "max_links": 150},
    ],
    "clearinghouse_cdfi": [
        {"url": "https://www.clearinghousecdfi.com/", "source_name": "Clearinghouse CDFI", "max_links": 150},
    ],
    "fiscal_sponsor_directory": [
        {"url": "https://www.fiscalsponsors.org/", "source_name": "National Network of Fiscal Sponsors", "max_links": 150},
    ],
    "pensacola_can_fiscal_sponsor": [
        {"url": "https://www.pensacolacan.org/", "source_name": "Pensacola Community Action Network", "max_links": 120},
    ],
    "cdfi_fund_directory": [
        {"url": "https://www.cdfifund.gov/", "source_name": "CDFI Fund", "max_links": 180},
    ],
    "giin_members": [
        {"url": "https://thegiin.org/members/", "source_name": "Global Impact Investing Network", "max_links": 250},
        {"url": "https://thegiin.org/investors-council/", "source_name": "GIIN Investors' Council", "max_links": 200},
    ],
    "mission_investors_exchange": [
        {"url": "https://missioninvestors.org/tools/search/mission-investment-database", "source_name": "Mission Investors Exchange", "max_links": 250},
    ],
    "angel_capital_association": [
        {"url": "https://angelcapitalassociation.org/", "source_name": "Angel Capital Association", "max_links": 200},
    ],
    "florida_funders": [
        {"url": "https://www.floridafunders.com/", "source_name": "Florida Funders", "max_links": 180},
    ],
}


@dataclass(frozen=True, slots=True)
class DiscoveryRunResult:
    planned_queries: int
    executed_queries: int
    discovered_results: int
    ingested_results: int
    review_folders_created: int
    errors: list[dict[str, str]]
    opportunities: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _result_payload(result: SearchResult, *, source_key: str, lane: str) -> dict[str, Any]:
    raw = dict(result.raw or {})
    raw.update({"source_key": source_key, "lane": lane})
    return {
        "external_id": result.external_id,
        "title": result.title,
        "funder": result.funder,
        "agency": result.agency,
        "description": result.description,
        "eligibility": result.eligibility,
        "geography": result.geography,
        "deadline": result.deadline,
        "award_floor": result.award_floor,
        "award_ceiling": result.award_ceiling,
        "source_url": result.source_url,
        "status": "DISCOVERED",
        "opportunity_type": _infer_opportunity_type(source_key, lane, result),
        "raw": raw,
    }


def _infer_opportunity_type(source_key: str, lane: str, result: SearchResult) -> str:
    text = " ".join(
        [
            source_key,
            lane,
            result.title or "",
            result.description or "",
            result.eligibility or "",
        ]
    ).lower()
    if "fiscal sponsor" in text or "fiscal sponsorship" in text:
        return "FISCAL_SPONSORSHIP"
    if "program related investment" in text or "program-related investment" in text or "recoverable grant" in text:
        return "PRI"
    if "angel" in text or "equity" in text or "venture capital" in text:
        return "ANGEL_INVESTMENT"
    if "impact investor" in text or "impact investment" in text or "mission investment" in text:
        return "IMPACT_INVESTMENT"
    if "cdfi" in text:
        return "CDFI_LOAN"
    if "kiva" in text or "microloan" in text or "zero interest" in text or "0%" in text:
        return "MICROLOAN"
    if "crowdfund" in text:
        return "CROWDFUNDING"
    if "loan" in text or "financing" in text:
        return "LOAN"
    if "sponsor" in text:
        return "SPONSORSHIP"
    return "GRANT"


def _adapter_for(source_key: str):
    if source_key == "federal_grants_gov":
        return GrantsGovAdapter()
    pages = OFFICIAL_SOURCE_PAGES.get(source_key)
    if pages:
        return OfficialFundingPageAdapter(source_key=source_key, pages=pages)
    return None


def _opportunity_from_payload(opportunity_id: int, payload: dict[str, Any]) -> Opportunity:
    amount = payload.get("award_ceiling") or payload.get("award_floor")
    return Opportunity(
        id=str(opportunity_id),
        title=str(payload.get("title") or "Funding opportunity"),
        funder=str(payload.get("funder") or payload.get("agency") or ""),
        description=str(payload.get("description") or ""),
        eligibility=str(payload.get("eligibility") or ""),
        deadline=str(payload.get("deadline") or "") or None,
        amount=float(amount) if isinstance(amount, (int, float)) else None,
        source_url=str(payload.get("source_url") or ""),
        nofo_text="",
        metadata={
            "opportunity_type": payload.get("opportunity_type"),
            "raw": payload.get("raw") or {},
        },
    )


def run_live_discovery(
    *,
    state: str = "Florida",
    counties: list[str] | None = None,
    cities: list[str] | None = None,
    lanes: list[str] | None = None,
    max_terms_per_lane: int = 2,
    per_query_limit: int = 15,
    maximum_queries: int = 100,
    minimum_review_score: int = 60,
    applicant_tax_status: TaxStatus = TaxStatus.PENDING_501C3,
    has_fiscal_sponsor: bool = False,
    create_review_folders: bool = True,
) -> DiscoveryRunResult:
    if maximum_queries < 1:
        raise ValueError("maximum_queries must be at least 1")
    if per_query_limit < 1:
        raise ValueError("per_query_limit must be at least 1")

    seed_catalog()
    plan = build_discovery_plan(
        state=state,
        counties=counties,
        cities=cities,
        lanes=lanes,
        max_terms_per_lane=max_terms_per_lane,
    )

    executed = 0
    discovered = 0
    ingested = 0
    review_count = 0
    errors: list[dict[str, str]] = []
    analyzed_rows: list[dict[str, Any]] = []
    dedupe: set[tuple[str, str]] = set()

    for row in plan:
        if executed >= maximum_queries:
            break

        source_key = str(row["source_key"])
        adapter = _adapter_for(source_key)
        if adapter is None:
            continue

        executed += 1
        request = SearchRequest(
            query=str(row["query"]),
            geography=str(row.get("geography") or "") or None,
            limit=per_query_limit,
            filters={"lane": row.get("lane")},
        )

        try:
            results: Iterable[SearchResult] = adapter.search(request)
            for result in results:
                discovered += 1
                dedupe_key = (
                    source_key,
                    (result.source_url or result.title).strip().lower(),
                )
                if dedupe_key in dedupe:
                    continue
                dedupe.add(dedupe_key)

                payload = _result_payload(result, source_key=source_key, lane=str(row.get("lane") or ""))
                opportunity_id = ingest_opportunity(source_key, payload)
                ingested += 1

                analyzed = analyze_opportunity(_opportunity_from_payload(opportunity_id, payload), generate_drafts=False)
                analyzed["source_key"] = source_key
                analyzed["lane"] = row.get("lane")
                analyzed["opportunity_type"] = payload.get("opportunity_type")
                analyzed_rows.append(analyzed)

                if create_review_folders:
                    folder = create_review_folder_from_analysis(
                        analyzed,
                        applicant_status=applicant_tax_status,
                        has_fiscal_sponsor=has_fiscal_sponsor,
                        minimum_score=minimum_review_score,
                    )
                    if folder:
                        analyzed["review_folder"] = folder
                        review_count += 1
        except Exception as exc:
            errors.append(
                {
                    "source_key": source_key,
                    "query": str(row.get("query") or ""),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    analyzed_rows.sort(
        key=lambda item: (
            bool(item.get("hard_reject")),
            -int(item.get("score", 0) or 0),
            -int(item.get("readiness_score", 0) or 0),
            str(item.get("title") or "").lower(),
        )
    )

    return DiscoveryRunResult(
        planned_queries=len(plan),
        executed_queries=executed,
        discovered_results=discovered,
        ingested_results=ingested,
        review_folders_created=review_count,
        errors=errors,
        opportunities=analyzed_rows,
    )
