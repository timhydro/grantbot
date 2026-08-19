from __future__ import annotations

import unittest
from unittest.mock import patch

from grantbot.api import funding_live_v24
from grantbot.automation.review_router import classify_funding_type
from grantbot.funding.adapters import SearchResult
from grantbot.funding.extended_catalog import EXTENDED_SOURCE_CATALOG
from grantbot.funding.lanes import SEARCH_LANES
from grantbot.funding.live_runner import (
    OFFICIAL_SOURCE_PAGES,
    _infer_opportunity_type,
    run_live_discovery,
)


class FundingLiveV24Tests(unittest.TestCase):
    def test_extended_catalog_has_core_alternative_capital_sources(self):
        keys = {item["source_key"] for item in EXTENDED_SOURCE_CATALOG}
        self.assertIn("kiva_us", keys)
        self.assertIn("cdfi_fund_directory", keys)
        self.assertIn("florida_community_loan_fund", keys)
        self.assertIn("fiscal_sponsor_directory", keys)
        self.assertIn("pensacola_can_fiscal_sponsor", keys)
        self.assertIn("impact_investor_search", keys)
        self.assertIn("angel_network_search", keys)

    def test_search_lanes_cover_non_grant_capital(self):
        for lane in (
            "cdfi",
            "microloan",
            "fiscal_sponsor",
            "pri",
            "angel_social_enterprise",
            "crowdfunding",
        ):
            self.assertIn(lane, SEARCH_LANES)
            self.assertTrue(SEARCH_LANES[lane])

    def test_live_runner_has_official_pages_for_actionable_sources(self):
        for source_key in (
            "kiva_us",
            "florida_community_loan_fund",
            "clearinghouse_cdfi",
            "fiscal_sponsor_directory",
            "pensacola_can_fiscal_sponsor",
            "cdfi_fund_directory",
        ):
            self.assertIn(source_key, OFFICIAL_SOURCE_PAGES)
            self.assertTrue(OFFICIAL_SOURCE_PAGES[source_key][0]["url"].startswith("https://"))

    def test_infer_opportunity_type_prefers_specific_capital_routes(self):
        result = SearchResult(
            external_id=None,
            title="Community Development Financial Institution housing financing",
            description="CDFI loan for supportive housing",
        )
        self.assertEqual(
            _infer_opportunity_type("florida_community_loan_fund", "cdfi", result),
            "CDFI_LOAN",
        )

        result = SearchResult(
            external_id=None,
            title="Fiscal Sponsorship Application",
            description="Apply for a fiscal sponsor",
        )
        self.assertEqual(
            _infer_opportunity_type("pensacola_can_fiscal_sponsor", "fiscal_sponsor", result),
            "FISCAL_SPONSORSHIP",
        )

        result = SearchResult(
            external_id=None,
            title="Zero interest microloan",
            description="Kiva crowdfunding loan",
        )
        self.assertEqual(
            _infer_opportunity_type("kiva_us", "microloan", result),
            "MICROLOAN",
        )

        result = SearchResult(
            external_id=None,
            title="Social enterprise angel investment",
            description="Equity investment into mission-driven business",
        )
        self.assertEqual(
            _infer_opportunity_type("angel_network_search", "angel_social_enterprise", result),
            "ANGEL_INVESTMENT",
        )

    def test_kiva_review_type_is_not_flattened_to_generic_loan(self):
        self.assertEqual(
            classify_funding_type("Kiva zero interest microloan for community enterprise"),
            "MICROLOAN_OR_CROWDFUNDED_LOAN",
        )

    def test_health_endpoint_shape_without_database_dependency(self):
        with patch.object(
            funding_live_v24,
            "registry_stats",
            return_value={"active_sources": 17},
        ):
            result = funding_live_v24.health()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["version"], 24)
        self.assertEqual(result["registered_sources"], 17)
        self.assertIn("kiva_us", result["live_page_adapters"])

    def test_query_limit_counts_only_executable_queries(self):
        plan = [
            {
                "source_key": "unsupported_source",
                "query": "ignored",
                "geography": "Florida",
                "lane": "grant",
            },
            {
                "source_key": "kiva_us",
                "query": "microloan Florida",
                "geography": "Florida",
                "lane": "microloan",
            },
            {
                "source_key": "kiva_us",
                "query": "zero interest loan Florida",
                "geography": "Florida",
                "lane": "microloan",
            },
        ]

        class EmptyAdapter:
            def search(self, request):
                return []

        def fake_adapter(source_key):
            return EmptyAdapter() if source_key == "kiva_us" else None

        with patch("grantbot.funding.live_runner.seed_catalog", return_value=1), patch(
            "grantbot.funding.live_runner.build_discovery_plan",
            return_value=plan,
        ), patch(
            "grantbot.funding.live_runner._adapter_for",
            side_effect=fake_adapter,
        ):
            result = run_live_discovery(
                maximum_queries=1,
                create_review_folders=False,
            )

        self.assertEqual(result.planned_queries, 3)
        self.assertEqual(result.executed_queries, 1)
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()
