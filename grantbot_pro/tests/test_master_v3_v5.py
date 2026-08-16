from __future__ import annotations

import unittest

from grantbot.automation.opportunity_pipeline import Opportunity, rank_opportunities
from grantbot.nofo.analyzer import analyze_nofo
from grantbot.writing.quality_gate import evaluate_draft


class MasterV3V5Tests(unittest.TestCase):
    def test_quality_rejects_unsupported_number(self) -> None:
        result = evaluate_draft(
            question="How many people?",
            draft="We will serve 500 people.",
            facts=[{"value": "People experiencing homelessness"}],
            max_words=100,
        )
        self.assertFalse(result.passed)
        self.assertIn("500", result.unsupported_numbers)

    def test_nofo_strong_fit(self) -> None:
        result = analyze_nofo(
            """
            Eligible applicants include nonprofit and faith-based organizations.
            Florida reentry homelessness supportive housing employment workforce
            development job training case management supportive services.
            1. Describe your organization mission?
            """
        )
        self.assertGreaterEqual(result.fit_score, 80)
        self.assertEqual(result.priority, "HIGH")

    def test_hard_reject(self) -> None:
        result = analyze_nofo(
            """
            Eligibility: Postdoctoral applicants only.
            This program funds research.
            """
        )
        self.assertTrue(result.hard_reject)
        self.assertEqual(result.priority, "REJECT")

    def test_rank(self) -> None:
        results = rank_opportunities(
            [
                Opportunity(
                    id="weak",
                    title="Museum",
                    description="Historic preservation",
                    deadline="2099-12-01",
                ),
                Opportunity(
                    id="strong",
                    title="Florida Reentry Housing Workforce",
                    description=(
                        "reentry homelessness housing employment workforce "
                        "supportive services Florida"
                    ),
                    eligibility="nonprofit organizations",
                    deadline="2099-12-01",
                ),
            ]
        )
        self.assertEqual(results[0]["id"], "strong")
        self.assertGreaterEqual(results[0]["score"], 80)


if __name__ == "__main__":
    unittest.main()
