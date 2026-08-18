from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grantbot.pipeline.live_queue_v16 import (
    _dedupe_hits,
    _fit,
    _normalize_hit,
    _priority,
    discover_ranked_queue,
    health,
)


class LiveQueueV16Tests(unittest.TestCase):
    def test_domain_scoring(self) -> None:
        score, domains, blockers = _fit(
            "Reentry supportive housing, workforce employment training, and case management",
            "Department of Housing",
        )
        self.assertEqual(score, 80)
        self.assertIn("reentry", domains)
        self.assertIn("housing", domains)
        self.assertEqual(blockers, [])

    def test_specialized_eligibility_reject(self) -> None:
        score, _, blockers = _fit(
            "Postdoctoral research fellowship",
            "Federal Agency",
        )
        self.assertEqual(score, 0)
        self.assertTrue(blockers)
        self.assertEqual(_priority(score, bool(blockers)), "REJECT")

    def test_normalize_search_hit(self) -> None:
        hit = _normalize_hit(
            {
                "id": "123",
                "number": "ABC-123",
                "title": "Workforce Reentry Program",
                "agencyCode": "DOL",
                "agencyName": "Department of Labor",
                "oppStatus": "posted",
                "alnist": ["17.000"],
            },
            "reentry",
        )
        self.assertEqual(hit["opportunity_id"], "123")
        self.assertEqual(hit["matched_keywords"], ["reentry"])

    def test_deduplicate_and_merge_keywords(self) -> None:
        hits = _dedupe_hits(
            [
                {"key": "1", "opportunity_id": "1", "matched_keywords": ["reentry"]},
                {"key": "1", "opportunity_id": "1", "matched_keywords": ["housing"]},
            ]
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["matched_keywords"], ["reentry", "housing"])

    def test_ranked_queue_persists(self) -> None:
        def fake_search(keyword: str, **_: object) -> list[dict[str, object]]:
            return [
                {
                    "key": "100",
                    "opportunity_id": "100",
                    "opportunity_number": "BGM-100",
                    "title": "Reentry supportive housing workforce employment training case management",
                    "agency_code": "HUD",
                    "agency": "Housing Agency",
                    "open_date": "08/01/2026",
                    "close_date": "10/01/2026",
                    "status": "posted",
                    "document_type": "synopsis",
                    "assistance_listings": ["14.000"],
                    "matched_keywords": [keyword],
                }
            ]

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "grantbot.db"
            with patch.dict(os.environ, {"GRANTBOT_DB_PATH": str(db_path)}):
                run = discover_ranked_queue(
                    keywords=["reentry", "housing"],
                    rows_per_keyword=2,
                    deep_limit=0,
                    searcher=fake_search,
                )
                self.assertEqual(run.unique_opportunities, 1)
                self.assertEqual(run.high_count, 1)
                self.assertTrue(db_path.exists())
                self.assertTrue(Path(run.output_path).exists())
                payload = json.loads(Path(run.output_path).read_text())
                self.assertEqual(payload["items"][0]["priority"], "HIGH")

    def test_health_initializes_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "grantbot.db"
            with patch.dict(os.environ, {"GRANTBOT_DB_PATH": str(db_path)}):
                result = health()
                self.assertTrue(result["healthy"])
                self.assertTrue(result["queue_tables_ready"])


if __name__ == "__main__":
    unittest.main()
