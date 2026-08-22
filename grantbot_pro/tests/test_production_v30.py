from __future__ import annotations

import unittest
from unittest.mock import patch

from grantbot import __version__
from grantbot.app import app
from grantbot.production.master_tool_v30 import run_adaptive_application_answer


class ProductionV30Tests(unittest.TestCase):
    def test_version_is_v30(self) -> None:
        self.assertEqual(__version__, "30.0.0")

    def test_v30_routes_are_authenticated(self) -> None:
        schema = app.openapi()
        for path, method in (
            ("/v30/production/status", "get"),
            ("/v30/production/answer", "post"),
            ("/v30/intelligence/status", "get"),
            ("/v30/intelligence/opportunity-score", "post"),
            ("/v30/intelligence/provenance", "post"),
            ("/v30/intelligence/consistency", "post"),
            ("/v30/intelligence/adversarial-panel", "post"),
        ):
            self.assertIn(path, schema["paths"])
            operation = schema["paths"][path][method]
            self.assertTrue(operation.get("security"), path)

    def test_adaptive_answer_attaches_provenance_and_telemetry(self) -> None:
        base = {
            "status": "READY_FOR_HUMAN_REVIEW",
            "final_answer": "The program combines transitional housing with workforce development.",
            "role_models": {
                "research": {"provider": "test", "model": "test/research", "mode": "test"},
                "writing": {"provider": "test", "model": "test/writing", "mode": "test"},
            },
            "artifact_sha256": "abc123",
            "deterministic_quality": {"passed": True},
            "claim_integrity": {"safe": True},
            "voice_integrity": {"passed": True},
        }
        facts = [
            {
                "fact_id": "fact-program",
                "fact_key": "program_model",
                "verification_state": "VERIFIED",
                "value": "The program combines transitional housing with workforce development.",
                "source": "approved-program-plan",
            }
        ]
        with patch(
            "grantbot.production.master_tool_v30.run_v29_application_answer",
            return_value=base,
        ), patch(
            "grantbot.production.master_tool_v30.current_facts",
            return_value=facts,
        ), patch(
            "grantbot.production.master_tool_v30._record_role_telemetry",
            return_value=[10, 11],
        ):
            result = run_adaptive_application_answer(
                dossier="Application dossier",
                question="Describe the program.",
                section_type="program",
            )

        self.assertEqual(result["version"], "30.0.0")
        self.assertEqual(result["adaptive_status"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(result["provenance_unresolved_count"], 0)
        self.assertEqual(result["sentence_provenance"][0]["support_status"], "SUPPORTED")
        self.assertEqual(result["telemetry_record_ids"], [10, 11])
        self.assertFalse(result["safe_to_submit"])
        self.assertTrue(result["human_review_required"])

    def test_unresolved_provenance_forces_remediation(self) -> None:
        base = {
            "status": "READY_FOR_HUMAN_REVIEW",
            "final_answer": "The program will serve 999 participants.",
            "role_models": {},
            "artifact_sha256": "abc123",
        }
        with patch(
            "grantbot.production.master_tool_v30.run_v29_application_answer",
            return_value=base,
        ), patch(
            "grantbot.production.master_tool_v30.current_facts",
            return_value=[],
        ), patch(
            "grantbot.production.master_tool_v30._record_role_telemetry",
            return_value=[],
        ):
            result = run_adaptive_application_answer(
                dossier="Application dossier",
                question="How many people will you serve?",
            )
        self.assertEqual(result["adaptive_status"], "REMEDIATION_REQUIRED")
        self.assertGreater(result["provenance_unresolved_count"], 0)
        self.assertTrue(result["adaptive_blockers"])

    def test_budget_and_workplan_must_be_supplied_together(self) -> None:
        with self.assertRaises(ValueError):
            run_adaptive_application_answer(
                dossier="Application dossier",
                question="Describe the program.",
                budget={"personnel": 1000.0},
                workplan=None,
            )

    def test_consistency_blocker_forces_remediation(self) -> None:
        base = {
            "status": "READY_FOR_HUMAN_REVIEW",
            "final_answer": "Personnel and transportation support the program.",
            "role_models": {},
            "artifact_sha256": "abc123",
        }
        facts = [
            {
                "fact_id": "fact-program",
                "verification_state": "VERIFIED",
                "value": "Personnel and transportation support the program.",
                "source": "approved-plan",
            }
        ]
        with patch(
            "grantbot.production.master_tool_v30.run_v29_application_answer",
            return_value=base,
        ), patch(
            "grantbot.production.master_tool_v30.current_facts",
            return_value=facts,
        ), patch(
            "grantbot.production.master_tool_v30._record_role_telemetry",
            return_value=[],
        ):
            result = run_adaptive_application_answer(
                dossier="Application dossier",
                question="Describe the program.",
                budget={"personnel": 50_000.0, "transportation": 10_000.0},
                workplan={"activity": "workforce support"},
                expected_budget_total=70_000.0,
            )
        self.assertEqual(result["adaptive_status"], "REMEDIATION_REQUIRED")
        self.assertTrue(any(item["severity"] == "BLOCKER" for item in result["consistency_issues"]))


if __name__ == "__main__":
    unittest.main()
