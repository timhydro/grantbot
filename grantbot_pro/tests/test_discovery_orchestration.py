from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from grantbot.discovery import orchestrator
from grantbot.discovery import source_health
from grantbot.discovery.pages import list_pages
from grantbot.funding.registry import seed_catalog


class _FakeBrave:
    enabled = True


class _FakeEngine:
    def __init__(self) -> None:
        self.brave = _FakeBrave()
        self.calls: list[tuple[str, str]] = []

    def grants_gov(self, **kwargs):
        self.calls.append(("GRANTS_GOV", str(kwargs["query"])))
        return {
            "seen": 2,
            "saved": 1,
            "duplicates": 1,
            "errors": 0,
            "results": [
                {
                    "opportunity_id": 1,
                    "title": "Federal Reentry Housing",
                    "source_url": "https://example.gov/1",
                    "deadline": "2026-10-01",
                    "duplicate": False,
                }
            ],
        }

    def crawl_registered_pages(self, **kwargs):
        self.calls.append(("REGISTERED_PAGES", str(kwargs["query"])))
        return {
            "seen": 1,
            "saved": 1,
            "duplicates": 0,
            "errors": 0,
            "results": [
                {
                    "opportunity_id": 2,
                    "title": "Florida Workforce Grant",
                    "source_url": "https://example.fl.gov/2",
                    "deadline": "2026-09-15",
                    "duplicate": False,
                }
            ],
        }

    def broad_web_search(self, **kwargs):
        self.calls.append(("BROAD_WEB", str(kwargs["plan_row"]["query"])))
        return {
            "seen": 1,
            "saved": 1,
            "duplicates": 0,
            "errors": 0,
            "results": [],
        }


class DiscoveryOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("GRANTBOT_DATABASE")
        os.environ["GRANTBOT_DATABASE"] = str(Path(self.tmp.name) / "grantbot.db")

    def tearDown(self) -> None:
        if self.old_db is None:
            os.environ.pop("GRANTBOT_DATABASE", None)
        else:
            os.environ["GRANTBOT_DATABASE"] = self.old_db
        self.tmp.cleanup()

    def test_fresh_database_page_listing_initializes_schema(self) -> None:
        seeded = seed_catalog()
        self.assertGreater(seeded, 0)
        self.assertEqual(list_pages(), [])
        self.assertEqual(list_pages("federal_grants_gov"), [])

    def test_plan_filters_conditional_and_investable_sources(self) -> None:
        plan = [
            {
                "source_key": "direct",
                "source_name": "Direct Source",
                "lane": "housing",
                "query": "housing Florida",
                "geography": "Florida",
            },
            {
                "source_key": "conditional",
                "source_name": "Conditional Source",
                "lane": "housing",
                "query": "supportive housing Florida",
                "geography": "Florida",
            },
            {
                "source_key": "angel",
                "source_name": "Angel Source",
                "lane": "investor",
                "query": "impact venture Florida",
                "geography": "Florida",
            },
        ]
        sources = {
            "direct": {
                "nonprofit_fit": "DIRECT",
                "requires_investable_entity": 0,
                "requires_subscription": 0,
                "requires_legal_review": 0,
            },
            "conditional": {
                "nonprofit_fit": "CONDITIONAL",
                "requires_investable_entity": 0,
                "requires_subscription": 0,
                "requires_legal_review": 1,
            },
            "angel": {
                "nonprofit_fit": "INDIRECT",
                "requires_investable_entity": 1,
                "requires_subscription": 0,
                "requires_legal_review": 1,
            },
        }
        with patch.object(orchestrator, "seed_catalog"), patch.object(
            orchestrator,
            "build_discovery_plan",
            return_value=plan,
        ), patch.object(
            orchestrator,
            "get_source",
            side_effect=lambda key: sources[key],
        ):
            result = orchestrator.plan_discovery_campaign(
                include_conditional=False,
                include_investment=False,
                max_queries=10,
            )
        self.assertEqual(result["query_count"], 1)
        self.assertEqual(result["plan"][0]["source_key"], "direct")

    def test_campaign_uses_dedicated_and_registered_connectors(self) -> None:
        plan = {
            "plan": [
                {
                    "source_key": "federal_grants_gov",
                    "source_name": "Grants.gov",
                    "lane": "reentry",
                    "query": "reentry Florida",
                    "geography": "United States",
                },
                {
                    "source_key": "florida_state_agencies",
                    "source_name": "Florida State Agency Funding",
                    "lane": "workforce",
                    "query": "workforce Florida",
                    "geography": "Florida",
                },
            ]
        }
        fake = _FakeEngine()

        def mode(_engine, row, *, broad_web):
            self.assertTrue(broad_web)
            if row["source_key"] == "federal_grants_gov":
                return "GRANTS_GOV", "DEDICATED_API"
            return "REGISTERED_PAGES", "1_REGISTERED_PAGE(S)"

        with patch.object(
            orchestrator,
            "plan_discovery_campaign",
            return_value=plan,
        ), patch.object(orchestrator, "_execution_mode", side_effect=mode):
            result = orchestrator.run_discovery_campaign(
                actor="writer@test",
                engine=fake,
                max_queries=2,
                per_query_limit=5,
            )
        self.assertEqual(result.status, "COMPLETE")
        self.assertEqual(result.attempted_count, 2)
        self.assertEqual(result.saved_count, 2)
        self.assertEqual(
            [call[0] for call in fake.calls],
            ["GRANTS_GOV", "REGISTERED_PAGES"],
        )
        stored = orchestrator.get_campaign(result.campaign_id)
        self.assertEqual(stored["saved_count"], 2)
        self.assertEqual(orchestrator.recent_campaigns(5)[0]["campaign_id"], result.campaign_id)

    def test_source_circuit_opens_after_three_failures_and_reset_closes_it(self) -> None:
        now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
        for index in range(3):
            source_health.record_failure(
                "unstable_source",
                mode="BROAD_WEB",
                error=f"failure {index + 1}",
                now=now,
            )
        available, reason = source_health.source_available(
            "unstable_source",
            now=now,
        )
        self.assertFalse(available)
        self.assertIn("CIRCUIT_OPEN_UNTIL", reason)
        reset = source_health.reset_source("unstable_source")
        self.assertEqual(reset["consecutive_failures"], 0)
        available, _ = source_health.source_available("unstable_source", now=now)
        self.assertTrue(available)

    def test_open_circuit_skips_source_without_execution(self) -> None:
        now = datetime.now(timezone.utc)
        for index in range(3):
            source_health.record_failure(
                "florida_state_agencies",
                mode="REGISTERED_PAGES",
                error=f"failure {index + 1}",
                now=now,
            )
        fake = _FakeEngine()
        plan = {
            "plan": [
                {
                    "source_key": "florida_state_agencies",
                    "source_name": "Florida State Agency Funding",
                    "lane": "housing",
                    "query": "housing Florida",
                    "geography": "Florida",
                }
            ]
        }
        with patch.object(
            orchestrator,
            "plan_discovery_campaign",
            return_value=plan,
        ):
            result = orchestrator.run_discovery_campaign(
                actor="writer@test",
                engine=fake,
                max_queries=1,
            )
        self.assertEqual(result.status, "NO_EXECUTABLE_SOURCES")
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
