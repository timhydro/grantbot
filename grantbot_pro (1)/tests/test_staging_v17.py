from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grantbot.review.staging_v17 import (
    create_workspace,
    get_workspace,
    health,
    resolve_risk,
    save_draft,
    transition_workspace,
    update_checklist_item,
)


class StagingV17Tests(unittest.TestCase):
    def _analysis(self, root: Path, opportunity_id: str = "TEST-17") -> None:
        blueprint_dir = root / "data" / "nofo_blueprints" / opportunity_id
        match_dir = root / "data" / "matching" / opportunity_id
        readiness_dir = root / "data" / "readiness" / opportunity_id
        blueprint_dir.mkdir(parents=True, exist_ok=True)
        match_dir.mkdir(parents=True, exist_ok=True)
        readiness_dir.mkdir(parents=True, exist_ok=True)

        (blueprint_dir / "application_blueprint.json").write_text(
            json.dumps(
                {
                    "opportunity_id": opportunity_id,
                    "title": "Reentry Housing Program",
                    "funder": "Housing Agency",
                    "application_questions": [
                        "Describe the community need?",
                        "Explain the project budget and match?",
                    ],
                    "submission_requirements": ["Submit through official portal."],
                    "required_attachments": ["Board authorization."],
                    "match_requirements": ["Document required match."],
                }
            ),
            encoding="utf-8",
        )
        (match_dir / "competitive_match.json").write_text(
            json.dumps(
                {
                    "opportunity_id": opportunity_id,
                    "title": "Reentry Housing Program",
                    "funder": "Housing Agency",
                    "final_score": 82,
                    "priority": "HIGH",
                    "blockers": [],
                }
            ),
            encoding="utf-8",
        )
        (readiness_dir / "compliance_readiness.json").write_text(
            json.dumps(
                {
                    "opportunity_id": opportunity_id,
                    "final_readiness_score": 88,
                    "missing_items": [],
                    "compliance_risks": ["Verify match financing."],
                    "required_attachments": ["Board authorization."],
                    "submission_requirements": ["Submit through official portal."],
                }
            ),
            encoding="utf-8",
        )

    def test_health_initializes_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "grantbot.db"
            with patch.dict(os.environ, {"GRANTBOT_DB_PATH": str(db)}):
                result = health()
                self.assertTrue(result["healthy"])
                self.assertTrue(result["human_approval_required"])
                self.assertFalse(result["submission_enabled"])

    def test_workspace_lifecycle_gates(self) -> None:
        module_root = Path(__file__).resolve().parents[1]
        opportunity_id = "TEST-17"
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "grantbot.db"
            with patch.dict(os.environ, {"GRANTBOT_DB_PATH": str(db)}):
                self._analysis(module_root, opportunity_id)
                try:
                    workspace = create_workspace(opportunity_id)
                    self.assertEqual(workspace["stage"], "DRAFTING")
                    self.assertEqual(len(workspace["writer_tasks"]), 2)
                    self.assertEqual(len(workspace["risks"]), 1)

                    workspace_id = workspace["workspace_id"]
                    for task in workspace["writer_tasks"]:
                        workspace = save_draft(
                            workspace_id,
                            task["task_id"],
                            response=f"Completed response for {task['category']}.",
                            status="READY_FOR_REVIEW",
                            provenance=[{"source": "verified:test", "note": "test evidence"}],
                        )

                    workspace = transition_workspace(
                        workspace_id,
                        target_stage="READY_FOR_REVIEW",
                        actor="reviewer",
                        note="All narrative tasks reviewed.",
                    )
                    self.assertEqual(workspace["stage"], "READY_FOR_REVIEW")

                    workspace = transition_workspace(
                        workspace_id,
                        target_stage="APPROVED",
                        actor="authorized-reviewer",
                        note="Human review approved the draft package.",
                    )
                    self.assertTrue(workspace["human_approved"])

                    with self.assertRaises(ValueError):
                        transition_workspace(
                            workspace_id,
                            target_stage="READY_FOR_SUBMISSION",
                            actor="authorized-reviewer",
                            note="Attempt before compliance cleanup.",
                        )

                    risk = workspace["risks"][0]
                    workspace = resolve_risk(
                        workspace_id,
                        risk["risk_id"],
                        actor="authorized-reviewer",
                        resolution_note="Verified financing documentation attached.",
                    )
                    for item in workspace["checklist"]:
                        workspace = update_checklist_item(
                            workspace_id,
                            item["checklist_id"],
                            status="VERIFIED",
                            actor="authorized-reviewer",
                            note="Verified against application package.",
                        )

                    workspace = transition_workspace(
                        workspace_id,
                        target_stage="READY_FOR_SUBMISSION",
                        actor="authorized-reviewer",
                        note="All V17 safety gates satisfied.",
                    )
                    self.assertEqual(workspace["stage"], "READY_FOR_SUBMISSION")
                    with self.assertRaises(ValueError):
                        transition_workspace(
                            workspace_id,
                            target_stage="SUBMITTED",
                            actor="authorized-reviewer",
                            note="V17 must block final submission.",
                        )
                    snapshot = module_root / "data" / "staging_v17" / workspace_id / "workspace.json"
                    self.assertTrue(snapshot.is_file())
                    loaded = get_workspace(workspace_id)
                    self.assertEqual(loaded["workspace_id"], workspace_id)
                finally:
                    for base in (
                        module_root / "data" / "nofo_blueprints" / opportunity_id,
                        module_root / "data" / "matching" / opportunity_id,
                        module_root / "data" / "readiness" / opportunity_id,
                    ):
                        if base.exists():
                            for child in base.iterdir():
                                child.unlink()
                            base.rmdir()


if __name__ == "__main__":
    unittest.main()
