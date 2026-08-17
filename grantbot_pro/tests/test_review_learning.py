from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from grantbot.learning import review_learning
from grantbot.writing.master_writer import write_answer


DIMENSIONS = {
    "funder_alignment": 90,
    "evidence_fidelity": 95,
    "requirement_compliance": 92,
    "clarity": 90,
    "persuasion": 88,
    "measurability": 90,
    "implementation_feasibility": 91,
    "financial_consistency": 94,
}


class _FakeProvider:
    def __init__(self) -> None:
        self.config = SimpleNamespace(model="fake-model")
        self.prompt = ""
        self.system = ""

    def generate(
        self,
        prompt: str,
        *,
        system: str,
        temperature: float,
    ) -> str:
        self.prompt = prompt
        self.system = system
        self.assert_temperature = temperature
        return "Broken Growth plans to serve 30 participants."


class ReviewLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("GRANTBOT_DATABASE")
        os.environ["GRANTBOT_DATABASE"] = str(Path(self.tmp.name) / "grantbot.db")
        self.workspace = {
            "workspace_id": "ws-review",
            "opportunity_id": "opp-review",
            "title": "Community Reentry Program",
            "funder": "U.S. Department of Example",
            "analysis": {"blueprint": {}},
            "writer_tasks": [
                {
                    "task_id": "task-1",
                    "question": "How many participants will the program serve?",
                    "category": "PROGRAM_NARRATIVE",
                }
            ],
        }
        self.source_revision = {
            "revision_id": "rev-ai-1",
            "workspace_id": "ws-review",
            "task_id": "task-1",
            "content": "Broken Growth plans to serve 30 participants.",
            "facts": [
                {
                    "id": "fact-1",
                    "key": "year_one_participants",
                    "value": "30 participants",
                    "status": "DRAFT",
                    "source": "planning record",
                }
            ],
            "quality": {"passed": True},
            "claims": {"safe": True},
        }

    def tearDown(self) -> None:
        if self.old_db is None:
            os.environ.pop("GRANTBOT_DATABASE", None)
        else:
            os.environ["GRANTBOT_DATABASE"] = self.old_db
        self.tmp.cleanup()

    def _review_patches(self):
        return (
            patch.object(review_learning, "get_workspace", return_value=self.workspace),
            patch.object(
                review_learning,
                "list_revisions",
                return_value=[self.source_revision],
            ),
            patch.object(
                review_learning,
                "save_revision",
                return_value={"revision_id": "rev-human-1", "version": 2},
            ),
            patch.object(review_learning, "save_draft"),
            patch.object(review_learning, "record_feedback"),
        )

    def test_human_approved_review_creates_curated_learning_example(self) -> None:
        patches = self._review_patches()
        for item in patches:
            item.start()
        try:
            result = review_learning.submit_review(
                workspace_id="ws-review",
                task_id="task-1",
                revision_id="rev-ai-1",
                decision="APPROVE",
                dimensions=DIMENSIONS,
                rationale="Accurate, compliant, concise, and ready for use.",
                edit_tags=["clearer opening", "future tense"],
                reviewer="reviewer@test",
                final_text="Broken Growth plans to serve 30 participants.",
            )
        finally:
            for item in reversed(patches):
                item.stop()

        self.assertEqual(result["decision"], "APPROVE")
        self.assertTrue(result["learning_example_created"])
        self.assertEqual(result["human_revision_id"], "rev-human-1")
        self.assertEqual(result["funder_archetype"], "government")
        self.assertTrue(result["claims"]["safe"])

        examples = review_learning.approved_examples(
            query="How many participants will the program serve?",
            section_type="program_narrative",
            funder_archetype="government",
            limit=3,
        )
        self.assertEqual(len(examples), 1)
        self.assertEqual(
            examples[0]["final_text"],
            "Broken Growth plans to serve 30 participants.",
        )
        profile = review_learning.learning_profile(
            section_type="program_narrative",
            funder_archetype="government",
        )
        self.assertEqual(profile["approved_count"], 1)
        self.assertEqual(profile["review_count"], 1)
        self.assertIn("human-adjudicated", profile["learning_policy"])

    def test_approval_blocks_unsupported_human_edit(self) -> None:
        patches = self._review_patches()
        for item in patches:
            item.start()
        try:
            with self.assertRaisesRegex(ValueError, "unsupported claims"):
                review_learning.submit_review(
                    workspace_id="ws-review",
                    task_id="task-1",
                    revision_id="rev-ai-1",
                    decision="APPROVE",
                    dimensions=DIMENSIONS,
                    rationale="Attempted approval.",
                    edit_tags=[],
                    reviewer="reviewer@test",
                    final_text="Broken Growth served 900 participants last year.",
                )
        finally:
            for item in reversed(patches):
                item.stop()

        self.assertEqual(
            review_learning.learning_profile()["approved_count"],
            0,
        )

    def test_approval_requires_strong_scorecard(self) -> None:
        weak = dict(DIMENSIONS)
        weak["evidence_fidelity"] = 50
        patches = self._review_patches()
        for item in patches:
            item.start()
        try:
            with self.assertRaisesRegex(ValueError, "every review dimension"):
                review_learning.submit_review(
                    workspace_id="ws-review",
                    task_id="task-1",
                    revision_id="rev-ai-1",
                    decision="APPROVE",
                    dimensions=weak,
                    rationale="Evidence score is too weak for approval.",
                    edit_tags=[],
                    reviewer="reviewer@test",
                    final_text="Broken Growth plans to serve 30 participants.",
                )
        finally:
            for item in reversed(patches):
                item.stop()

    def test_writer_reference_examples_are_explicitly_style_only(self) -> None:
        provider = _FakeProvider()
        result = write_answer(
            question="How many participants will the program serve?",
            section="program_design",
            facts=[
                {
                    "id": "fact-1",
                    "category": "program",
                    "key": "participants",
                    "value": "30 participants",
                    "status": "DRAFT",
                    "source": "planning record",
                }
            ],
            approved_examples=[
                {
                    "final_text": "A prior approved example claimed 999 participants.",
                    "section_type": "program_design",
                    "reviewer_score": 95,
                }
            ],
            learning_profile={
                "approved_count": 4,
                "common_edit_tags": [["concise", 3]],
            },
            provider=provider,
        )
        self.assertIsNotNone(result.draft)
        self.assertIn("STYLE/STRUCTURE ONLY", provider.prompt)
        self.assertIn("never factual evidence", provider.system.lower())
        self.assertIn("999 participants", provider.prompt)
        self.assertNotIn("999 participants", result.draft or "")


if __name__ == "__main__":
    unittest.main()
