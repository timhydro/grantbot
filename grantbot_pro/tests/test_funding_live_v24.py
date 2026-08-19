from __future__ import annotations

from grantbot.funding.live_runner import (
    OFFICIAL_SOURCE_PAGES,
    _infer_opportunity_type,
)
from grantbot.funding.adapters import SearchResult
from grantbot.funding.extended_catalog import EXTENDED_SOURCE_CATALOG
from grantbot.funding.lanes import SEARCH_LANES


def test_extended_catalog_has_core_alternative_capital_sources():
    keys = {item["source_key"] for item in EXTENDED_SOURCE_CATALOG}
    assert "kiva_us" in keys
    assert "cdfi_fund_directory" in keys
    assert "florida_community_loan_fund" in keys
    assert "fiscal_sponsor_directory" in keys
    assert "pensacola_can_fiscal_sponsor" in keys
    assert "impact_investor_search" in keys
    assert "angel_network_search" in keys


def test_search_lanes_cover_non_grant_capital():
    for lane in (
        "cdfi",
        "microloan",
        "fiscal_sponsor",
        "pri",
        "angel_social_enterprise",
        "crowdfunding",
    ):
        assert lane in SEARCH_LANES
        assert SEARCH_LANES[lane]


def test_live_runner_has_official_pages_for_actionable_sources():
    for source_key in (
        "kiva_us",
        "florida_community_loan_fund",
        "clearinghouse_cdfi",
        "fiscal_sponsor_directory",
        "pensacola_can_fiscal_sponsor",
        "cdfi_fund_directory",
    ):
        assert source_key in OFFICIAL_SOURCE_PAGES
        assert OFFICIAL_SOURCE_PAGES[source_key][0]["url"].startswith("https://")


def test_infer_opportunity_type_prefers_specific_capital_routes():
    result = SearchResult(
        external_id=None,
        title="Community Development Financial Institution housing financing",
        description="CDFI loan for supportive housing",
    )
    assert _infer_opportunity_type("florida_community_loan_fund", "cdfi", result) == "CDFI_LOAN"

    result = SearchResult(
        external_id=None,
        title="Fiscal Sponsorship Application",
        description="Apply for a fiscal sponsor",
    )
    assert _infer_opportunity_type("pensacola_can_fiscal_sponsor", "fiscal_sponsor", result) == "FISCAL_SPONSORSHIP"

    result = SearchResult(
        external_id=None,
        title="Zero interest microloan",
        description="Kiva crowdfunding loan",
    )
    assert _infer_opportunity_type("kiva_us", "microloan", result) == "MICROLOAN"

    result = SearchResult(
        external_id=None,
        title="Social enterprise angel investment",
        description="Equity investment into mission-driven business",
    )
    assert _infer_opportunity_type("angel_network_search", "angel_social_enterprise", result) == "ANGEL_INVESTMENT"
