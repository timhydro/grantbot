from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grantbot.risk import engine


class RiskIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("GRANTBOT_DATABASE")
        os.environ["GRANTBOT_DATABASE"] = str(Path(self.tmp.name) / "grantbot.db")
        self.base = {
            "workspace_id": "ws-risk",
            "opportunity_id": "opp-risk",
            "applicant_role": "DIRECT_APPLICANT",
            "eligibility_blockers": [],
            "acquisition_status": "FULL_NOFO_VALIDATED",
            "requirement_count": 12,
            "blocking_requirement_count": 0,
            "budget_required": False,
            "match_required": False,
            "latest_budget": None,
            "budget_approved": False,
            "budget_blockers": [],
            "budget_warnings": [],
            "days_to_deadline": 90,
            "readiness_score": 92,
            "competitive_score": 82,
            "open_risk_count": 0,
            "pending_checklist_count": 0,
            "draft_count": 5,
            "incomplete_draft_count": 0,
        }

    def tearDown(self) -> None:
        if self.old_db is None:
            os.environ.pop("GRANTBOT_DATABASE", None)
        else:
            os.environ["GRANTBOT_DATABASE"] = self.old_db
        self.tmp.cleanup()

    def test_low_risk_direct_application_proceeds(self) -> None:
        result = engine.calculate_risk(dict(self.base))
        self.assertEqual(result["decision"], "PROCEED")
        self.assertEqual(result["risk_band"], "LOW")
        self.assertLess(result["risk_index"], 25)
        self.assertEqual(result["hard_blockers"], [])
        self.assertIn("not an award probability", result["methodology_note"])

    def test_ineligible_application_is_rejected(self) -> None:
        inputs = dict(self.base)
        inputs["applicant_role"] = "REJECT"
        inputs["eligibility_blockers"] = ["Nonprofits are not eligible applicants."]
        result = engine.calculate_risk(inputs)
        self.assertEqual(result["decision"], "REJECT")
        self.assertTrue(result["hard_blockers"])
        self.assertGreaterEqual(result["risk_index"], 25)

    def test_expired_deadline_is_rejected(self) -> None:
        inputs = dict(self.base)
        inputs["days_to_deadline"] = -1
        result = engine.calculate_risk(inputs)
        self.assertEqual(result["decision"], "REJECT")
        self.assertIn("submission deadline has passed", result["hard_blockers"])

    def test_requirement_and_budget_failures_hold_application(self) -> None:
        inputs = dict(self.base)
        inputs.update(
            {
                "blocking_requirement_count": 3,
                "budget_required": True,
                "latest_budget": {"budget_id": "b1"},
                "budget_blockers": ["Grant request does not match narrative"],
                "budget_approved": False,
            }
        )
        result = engine.calculate_risk(inputs)
        self.assertEqual(result["decision"], "HOLD")
        joined = " | ".join(result["hard_blockers"])
        self.assertIn("authoritative mandatory/conditional", joined)
        self.assertIn("financial consistency", joined)

    def test_immutable_risk_history_versions(self) -> None:
        calculated = engine.calculate_risk(dict(self.base))
        evaluated = dict(calculated)
        evaluated["inputs"] = dict(self.base)
        with patch.object(engine, "evaluate_workspace_risk", return_value=evaluated):
            first = engine.assess_workspace_risk("ws-risk", actor="reviewer@test")
            second = engine.assess_workspace_risk("ws-risk", actor="reviewer@test")
        self.assertEqual(first.version, 1)
        self.assertEqual(second.version, 2)
        history = engine.risk_history("ws-risk")
        self.assertEqual([item["version"] for item in history], [2, 1])
        self.assertEqual(history[0]["created_by"], "reviewer@test")
        self.assertTrue(history[0]["input_sha256"])


if __name__ == "__main__":
    unittest.main()
