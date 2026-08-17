from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grantbot.command_center import service


class CommandCenterTests(unittest.TestCase):
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

    @staticmethod
    def _workspace() -> dict:
        return {
            "workspace_id": "ws-1",
            "opportunity_id": "opp-1",
            "title": "Reentry Housing Grant",
            "funder": "Test Agency",
            "stage": "DRAFTING",
            "readiness_score": 82,
            "competitive_score": 77,
            "human_approved": False,
            "analysis": {
                "blueprint": {
                    "submission_deadline": "2026-09-01",
                }
            },
            "writer_tasks": [
                {
                    "task_id": "task-1",
                    "status": "DRAFT",
                    "response": "",
                }
            ],
            "risks": [
                {"risk_id": "risk-1", "status": "OPEN"}
            ],
            "checklist": [
                {"checklist_id": "check-1", "status": "PENDING"}
            ],
            "updated_at": "2026-08-17T12:00:00+00:00",
        }

    def test_empty_portfolios_are_valid_and_do_not_invent_money(self) -> None:
        with patch.object(service, "list_workspaces", return_value=[]), patch.object(
            service,
            "list_awards",
            return_value=[],
        ):
            applications = service.application_portfolio(as_of="2026-08-17")
            awards = service.award_portfolio(as_of="2026-08-17")
        self.assertEqual(applications["application_count"], 0)
        self.assertEqual(applications["latest_requested_amount_total"], 0)
        self.assertEqual(awards["award_count"], 0)
        self.assertEqual(awards["total_awarded_amount"], 0)

    def test_application_portfolio_separates_requested_from_awarded_value(self) -> None:
        summary = {"workspace_id": "ws-1"}
        budget_gate = {
            "budget_required": True,
            "match_required": False,
            "approved": True,
            "blockers": [],
            "warnings": [],
            "latest_budget": {
                "budget_id": "budget-1",
                "calculation": {"grant_request": 250000.0},
            },
        }
        risk = {
            "assessment_id": "assessment-1",
            "version": 2,
            "risk_index": 31,
            "risk_band": "ELEVATED",
            "decision": "PROCEED_WITH_CONTROLS",
            "confidence_score": 88,
            "hard_blockers": [],
            "created_at": "2026-08-17T12:00:00+00:00",
        }
        with patch.object(service, "list_workspaces", return_value=[summary]), patch.object(
            service,
            "get_workspace",
            return_value=self._workspace(),
        ), patch.object(
            service,
            "requirement_summary",
            return_value={"requirement_count": 8, "blocking_count": 1},
        ), patch.object(
            service,
            "budget_consistency",
            return_value=budget_gate,
        ), patch.object(
            service,
            "latest_risk",
            return_value=risk,
        ):
            result = service.application_portfolio(as_of="2026-08-17")
        self.assertEqual(result["application_count"], 1)
        self.assertEqual(result["latest_requested_amount_total"], 250000.0)
        self.assertEqual(
            result["financially_approved_requested_amount_total"],
            250000.0,
        )
        self.assertIn("not awards", result["financial_semantics"])
        row = result["applications"][0]
        self.assertEqual(row["material_blocker_count"], 4)
        self.assertEqual(row["deadline_state"], "UPCOMING")
        self.assertEqual(row["risk"]["risk_band"], "ELEVATED")

    def test_deadlines_combine_application_reports_and_compliance_tasks(self) -> None:
        application_payload = {
            "applications": [
                {
                    "workspace_id": "ws-1",
                    "title": "Application",
                    "funder": "Agency",
                    "stage": "DRAFTING",
                    "terminal_stage": False,
                    "deadline": {"date": "2026-08-20"},
                }
            ]
        }
        award = {
            "award_id": "awd-1",
            "funder": "Foundation",
        }
        dashboard = {
            "reports": [
                {
                    "report_id": "rpt-1",
                    "report_type": "PROGRAMMATIC",
                    "due_date": "2026-08-25",
                    "required": 1,
                    "status": "DUE",
                }
            ],
            "compliance_tasks": [
                {
                    "task_id": "task-1",
                    "description": "Certification",
                    "due_date": "2026-08-10",
                    "required": 1,
                    "status": "OPEN",
                }
            ],
        }
        with patch.object(
            service,
            "application_portfolio",
            return_value=application_payload,
        ), patch.object(service, "list_awards", return_value=[award]), patch.object(
            service,
            "award_dashboard",
            return_value=dashboard,
        ):
            result = service.deadline_portfolio(
                as_of="2026-08-17",
                days=30,
                include_past_due=True,
            )
        self.assertEqual(result["deadline_count"], 3)
        self.assertEqual(result["past_due_count"], 1)
        self.assertEqual(result["blocking_past_due_count"], 1)
        self.assertEqual(result["due_within_7_days"], 1)
        self.assertEqual(
            result["deadlines"][0]["item_type"],
            "AWARD_COMPLIANCE_TASK",
        )

    def test_portfolio_risks_surface_unassessed_and_postaward_watch_items(self) -> None:
        applications = {
            "applications": [
                {
                    "workspace_id": "ws-1",
                    "title": "Unassessed application",
                    "risk": None,
                    "risk_assessment_state": "NOT_ASSESSED",
                    "material_blocker_count": 2,
                    "deadline_state": "CRITICAL",
                }
            ]
        }
        awards = {
            "awards": [
                {
                    "award_id": "awd-1",
                    "title": "Active award",
                    "financial_risk_band": "ELEVATED",
                    "financial_risk_score": 44,
                    "overdue_report_count": 1,
                    "overdue_task_count": 0,
                }
            ]
        }
        with patch.object(
            service,
            "application_portfolio",
            return_value=applications,
        ), patch.object(
            service,
            "award_portfolio",
            return_value=awards,
        ):
            result = service.portfolio_risks(as_of="2026-08-17")
        self.assertEqual(result["risk_item_count"], 2)
        self.assertEqual(result["risks"][0]["risk_type"], "AWARD")
        self.assertIn("not an award-probability", result["methodology_note"])

    def test_summary_preserves_discovery_learning_and_financial_semantics(self) -> None:
        applications = {
            "application_count": 2,
            "stage_counts": {"DRAFTING": 2},
            "human_approved_count": 0,
            "blocked_application_count": 1,
            "unassessed_risk_count": 1,
            "past_due_application_count": 0,
            "latest_requested_amount_total": 300000.0,
            "financially_approved_requested_amount_total": 200000.0,
        }
        awards = {
            "award_count": 1,
            "active_award_count": 1,
            "total_awarded_amount": 100000.0,
            "active_awarded_amount": 100000.0,
            "active_spent": 25000.0,
            "active_remaining": 75000.0,
            "overdue_report_count": 0,
            "overdue_compliance_task_count": 0,
            "financial_watch_count": 0,
        }
        deadlines = {
            "deadline_count": 2,
            "past_due_count": 0,
            "blocking_past_due_count": 0,
            "due_within_7_days": 1,
            "due_within_30_days": 2,
        }
        discovery = {
            "source_count": 5,
            "circuit_open_count": 1,
            "campaigns": [{"campaign_id": "campaign-1"}],
        }
        learning = {
            "review_count": 8,
            "approved_count": 5,
            "approval_rate": 0.625,
            "average_approved_score": 91.0,
            "common_edit_tags": [["clarity", 3]],
        }
        with patch.object(
            service,
            "application_portfolio",
            return_value=applications,
        ), patch.object(
            service,
            "award_portfolio",
            return_value=awards,
        ), patch.object(
            service,
            "deadline_portfolio",
            return_value=deadlines,
        ), patch.object(
            service,
            "discovery_health",
            return_value=discovery,
        ), patch.object(
            service,
            "learning_profile",
            return_value=learning,
        ):
            result = service.portfolio_summary(as_of="2026-08-17")
        self.assertEqual(result["applications"]["application_count"], 2)
        self.assertEqual(result["awards"]["total_awarded_amount"], 100000.0)
        self.assertEqual(result["discovery"]["circuit_open_count"], 1)
        self.assertEqual(result["review_learning"]["approved_count"], 5)
        self.assertIn("not awards", result["financial_semantics"]["requested_amounts"])
        self.assertFalse(result["autonomous_submission_enabled"])


if __name__ == "__main__":
    unittest.main()
