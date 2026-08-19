from __future__ import annotations

from grantbot.funding.extended_catalog import EXTENDED_SOURCE_CATALOG
from grantbot.funding.lanes import DEFAULT_PRIORITY_LANES, SEARCH_LANES
from grantbot.funding.planner import LANE_SOURCE_MAP


def test_extended_catalog_contains_core_alternative_capital_sources():
    keys = {item["source_key"] for item in EXTENDED_SOURCE_CATALOG}
    assert "kiva_us" in keys
    assert "cdfi_fund_directory" in keys
    assert "florida_community_loan_fund" in keys
    assert "fiscal_sponsor_directory" in keys
    assert "impact_investor_search" in keys
    assert "angel_network_search" in keys


def test_alternative_capital_lanes_are_enabled_by_default():
    for lane in ("cdfi", "microloan", "fiscal_sponsor", "crowdfunding", "pri", "angel_social_enterprise"):
        assert lane in DEFAULT_PRIORITY_LANES
        assert SEARCH_LANES[lane]


def test_lane_source_routing_is_specific():
    assert "CDFI" in LANE_SOURCE_MAP["cdfi"]
    assert "FISCAL_SPONSOR" in LANE_SOURCE_MAP["fiscal_sponsor"]
    assert "CROWDFUNDING_LENDER" in LANE_SOURCE_MAP["microloan"]
    assert "ANGEL_NETWORK" in LANE_SOURCE_MAP["angel_social_enterprise"]
    assert "GOVERNMENT" not in LANE_SOURCE_MAP["angel_social_enterprise"]
