from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grantbot.budget import workspace as budgets


class BudgetConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("GRANTBOT_DATABASE")
        os.environ["GRANTBOT_DATABASE"] = str(Path(self.tmp.name) / "grantbot.db")
        self.workspace = {
            "workspace_id": "ws1",
            "analysis": {
                "blueprint": {
                    "award_floor": 500.0,
                    "award_ceiling": 5000.0,
                    "budget_requirements": ["Provide a project budget."],
                }
            },
            "writer_tasks": [],
        }
        self.requirements = (True, False, ["Provide a project budget."])
        self.narratives = [
            {
                "source": "revision:1",
                "text": (
                    "The grant request is $1,000. "
                    "The total project cost is $1,200. "
                    "The cash match is $200. "
                    "The indirect rate is 0%. "
                    "The program will serve 20 participants and provide 10 housing units."
                ),
            }
        ]
        self.patches = [
            patch.object(
                budgets,
                "get_workspace",
                side_effect=lambda _: dict(self.workspace),
            ),
            patch.object(
                budgets,
                "_budget_requirement_state",
                side_effect=lambda _: self.requirements,
            ),
            patch.object(
                budgets,
                "_narrative_sources",
                side_effect=lambda _: list(self.narratives),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        if self.old_db is None:
            os.environ.pop("GRANTBOT_DATABASE", None)
        else:
            os.environ["GRANTBOT_DATABASE"] = self.old_db
        self.tmp.cleanup()

    def _save(self, *, cash_match: float = 200.0) -> dict:
        return budgets.save_workspace_budget(
            "ws1",
            items=[
                {
                    "category": "PROGRAM",
                    "description": "Program delivery",
                    "quantity": 1,
                    "unit_cost": 1000,
                    "months": 1,
                }
            ],
            cash_match=cash_match,
            participant_count=20,
            housing_unit_count=10,
            actor="writer@test",
        )

    def test_budget_versioning_approval_and_narrative_consistency(self) -> None:
        first = self._save()
        self.assertEqual(first["version"], 1)
        gate = budgets.budget_consistency("ws1")
        self.assertIn("Latest budget version lacks financial approval", gate["blockers"])
        approved = budgets.approve_budget(
            "ws1",
            first["budget_id"],
            actor="finance@test",
            note="Verified against application instructions.",
        )
        self.assertTrue(approved["approved"])
        gate = budgets.budget_consistency("ws1")
        self.assertTrue(gate["ready"], gate["blockers"])

        second = self._save()
        self.assertEqual(second["version"], 2)
        self.assertFalse(second["approved"])
        gate = budgets.budget_consistency("ws1")
        self.assertFalse(gate["ready"])
        self.assertIn("Latest budget version lacks financial approval", gate["blockers"])
        history = budgets.budget_history("ws1")
        self.assertEqual([item["version"] for item in history], [2, 1])

    def test_narrative_amount_mismatch_blocks(self) -> None:
        first = self._save()
        budgets.approve_budget(
            "ws1",
            first["budget_id"],
            actor="finance@test",
            note="Approved.",
        )
        self.narratives[0]["text"] = "The grant request is $900."
        gate = budgets.budget_consistency("ws1")
        self.assertFalse(gate["ready"])
        self.assertTrue(
            any("does not match budget value" in item for item in gate["blockers"])
        )

    def test_award_ceiling_and_match_requirement_block(self) -> None:
        self.workspace["analysis"]["blueprint"]["award_ceiling"] = 900.0
        self.requirements = (True, True, ["Budget and match are required."])
        self.narratives[0]["text"] = (
            "The grant request is $1,000. The total project cost is $1,000."
        )
        self._save(cash_match=0)
        gate = budgets.budget_consistency("ws1", require_approval=False)
        self.assertTrue(any("exceeds award ceiling" in item for item in gate["blockers"]))
        self.assertTrue(
            any("no cash or in-kind match" in item for item in gate["blockers"])
        )

    def test_approved_prior_version_does_not_approve_new_version(self) -> None:
        first = self._save()
        budgets.approve_budget(
            "ws1",
            first["budget_id"],
            actor="finance@test",
            note="Approved v1.",
        )
        second = self._save()
        with self.assertRaisesRegex(ValueError, "latest budget version"):
            budgets.approve_budget(
                "ws1",
                first["budget_id"],
                actor="finance@test",
                note="Attempt stale approval.",
            )
        self.assertFalse(budgets.get_budget(second["budget_id"])["approved"])


if __name__ == "__main__":
    unittest.main()
