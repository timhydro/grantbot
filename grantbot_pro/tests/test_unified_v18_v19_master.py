from __future__ import annotations

import unittest

from grantbot.budget.engine import calculate_budget
from grantbot.claims.checker import check_claims
from grantbot.outcomes.logic_model import validate_logic_model


class UnifiedMasterTests(unittest.TestCase):
    def test_budget_is_deterministic(self) -> None:
        result = calculate_budget(
            items=[
                {
                    "category": "PERSONNEL",
                    "description": "Program coordinator",
                    "quantity": 1,
                    "unit_cost": 5000,
                    "months": 12,
                }
            ],
            indirect_rate_percent=10,
            cash_match=1000,
            participant_count=20,
        )
        self.assertEqual(result["direct_total"], 60000.0)
        self.assertEqual(result["indirect_amount"], 6000.0)
        self.assertEqual(result["grant_request"], 66000.0)
        self.assertEqual(result["total_project_cost"], 67000.0)
        self.assertEqual(result["cost_per_participant"], 3350.0)

    def test_claim_checker_blocks_unsupported_number(self) -> None:
        facts = [
            {
                "id": 1,
                "fact_key": "mission",
                "value": "The program provides supportive housing and workforce development.",
                "status": "APPROVED",
            }
        ]
        result = check_claims("The program will serve 500 people.", facts)
        self.assertFalse(result["safe"])
        self.assertGreater(result["unsafe_sentence_count"], 0)

    def test_projection_requires_prospective_language(self) -> None:
        facts = [
            {
                "id": 2,
                "fact_key": "planned_housing",
                "value": "10 tiny homes",
                "status": "DRAFT",
            }
        ]
        unsafe = check_claims("The organization operates 10 tiny homes.", facts)
        safe = check_claims("The organization plans to develop 10 tiny homes.", facts)
        self.assertFalse(unsafe["safe"])
        self.assertTrue(safe["safe"])

    def test_logic_model_validation(self) -> None:
        result = validate_logic_model(
            {
                "need": "Housing instability",
                "inputs": ["staff"],
                "activities": ["case management"],
                "outputs": ["participants served"],
                "short_term_outcomes": ["stability"],
                "intermediate_outcomes": ["employment"],
                "long_term_impact": ["independence"],
                "metrics": [
                    {
                        "name": "housing retention",
                        "target": "target set by approved plan",
                        "timeframe": "12 months",
                        "measurement_method": "case management records",
                    }
                ],
            }
        )
        self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()
