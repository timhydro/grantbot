from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from grantbot.postaward import service


class PostAwardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("GRANTBOT_DATABASE")
        os.environ["GRANTBOT_DATABASE"] = str(Path(self.tmp.name) / "grantbot.db")
        self.award = service.create_award(
            award_number="BGM-2026-001",
            title="Housing and Reentry Demonstration",
            funder="Test Funder",
            award_amount=120000,
            start_date="2026-01-01",
            end_date="2026-12-31",
            terms_source="signed-award.pdf#page=1",
            actor="authorized@test",
            opportunity_id="opp-1",
        )

    def tearDown(self) -> None:
        if self.old_db is None:
            os.environ.pop("GRANTBOT_DATABASE", None)
        else:
            os.environ["GRANTBOT_DATABASE"] = self.old_db
        self.tmp.cleanup()

    def test_award_requires_valid_period_and_unique_number(self) -> None:
        with self.assertRaisesRegex(ValueError, "end_date"):
            service.create_award(
                award_number="BAD-DATES",
                title="Bad",
                funder="Test Funder",
                award_amount=1,
                start_date="2026-12-31",
                end_date="2026-01-01",
                terms_source="award.pdf",
                actor="authorized@test",
            )
        with self.assertRaisesRegex(ValueError, "already exists"):
            service.create_award(
                award_number="BGM-2026-001",
                title="Duplicate",
                funder="Test Funder",
                award_amount=120000,
                start_date="2026-01-01",
                end_date="2026-12-31",
                terms_source="award.pdf",
                actor="authorized@test",
            )

    def test_financial_exposure_uses_recorded_run_rate_not_award_probability(self) -> None:
        award_id = self.award["award_id"]
        service.add_expenditure(
            award_id=award_id,
            transaction_date="2026-01-20",
            category="Personnel",
            amount=30000,
            description="Program salaries",
            source_reference="ledger:jan",
            actor="finance@test",
        )
        service.add_expenditure(
            award_id=award_id,
            transaction_date="2026-03-20",
            category="Housing",
            amount=30000,
            description="Eligible housing costs",
            source_reference="ledger:mar",
            actor="finance@test",
        )
        exposure = service.financial_exposure(
            award_id,
            as_of="2026-04-01",
        )
        self.assertEqual(exposure["spent"], 60000.0)
        self.assertGreater(exposure["run_rate_projected_total_spend"], 120000)
        self.assertIn("overrun", " ".join(exposure["signals"]).lower())
        self.assertIn("not a probability", exposure["methodology_note"])

    def test_report_submission_requires_evidence_and_acceptance_follows_submission(self) -> None:
        award_id = self.award["award_id"]
        report = service.add_report(
            award_id=award_id,
            report_type="PROGRAMMATIC",
            due_date="2026-04-30",
            source_reference="award.pdf#reporting",
            actor="writer@test",
            required=True,
        )
        with self.assertRaisesRegex(ValueError, "must be SUBMITTED"):
            service.set_report_status(
                award_id=award_id,
                report_id=report["report_id"],
                status="ACCEPTED",
                actor="reviewer@test",
                evidence_reference="funder-email:accepted",
            )
        submitted = service.set_report_status(
            award_id=award_id,
            report_id=report["report_id"],
            status="SUBMITTED",
            actor="reviewer@test",
            evidence_reference="portal-confirmation:123",
        )
        self.assertEqual(submitted["status"], "SUBMITTED")
        accepted = service.set_report_status(
            award_id=award_id,
            report_id=report["report_id"],
            status="ACCEPTED",
            actor="reviewer@test",
            evidence_reference="funder-email:accepted",
        )
        self.assertEqual(accepted["status"], "ACCEPTED")

    def test_required_compliance_task_cannot_be_not_applicable(self) -> None:
        award_id = self.award["award_id"]
        task = service.add_compliance_task(
            award_id=award_id,
            task_type="PROCUREMENT",
            description="Complete required procurement certification",
            source_reference="award.pdf#procurement",
            actor="reviewer@test",
            required=True,
        )
        with self.assertRaisesRegex(ValueError, "Required compliance tasks"):
            service.set_compliance_task_status(
                award_id=award_id,
                task_id=task["task_id"],
                status="NOT_APPLICABLE",
                actor="authorized@test",
                evidence_note="Attempted bypass",
                evidence_reference="memo:1",
                allow_not_applicable=True,
            )

    def test_metric_measurements_preserve_evidence_and_target_state(self) -> None:
        award_id = self.award["award_id"]
        metric = service.add_metric(
            award_id=award_id,
            name="Participants stably housed",
            unit="participants",
            target=40,
            target_date="2026-12-31",
            source_reference="award.pdf#performance",
            actor="reviewer@test",
            baseline=0,
        )
        service.add_measurement(
            award_id=award_id,
            metric_id=metric["metric_id"],
            measured_on="2026-06-30",
            value=22,
            evidence_reference="case-management-export:2026Q2",
            actor="reviewer@test",
        )
        dashboard = service.award_dashboard(
            award_id,
            as_of="2026-06-30",
        )
        self.assertEqual(len(dashboard["metrics"]), 1)
        self.assertFalse(dashboard["metrics"][0]["target_met"])
        self.assertEqual(
            dashboard["metrics"][0]["latest_measurement"]["evidence_reference"],
            "case-management-export:2026Q2",
        )
        self.assertTrue(dashboard["state_fingerprint_sha256"])

    def test_closeout_is_hard_gated_and_closed_award_becomes_immutable(self) -> None:
        award_id = self.award["award_id"]
        report = service.add_report(
            award_id=award_id,
            report_type="CLOSEOUT",
            due_date="2027-01-30",
            source_reference="award.pdf#closeout",
            actor="writer@test",
            required=True,
        )
        task = service.add_compliance_task(
            award_id=award_id,
            task_type="PROPERTY",
            description="Complete final property inventory certification",
            source_reference="award.pdf#property",
            actor="reviewer@test",
            required=True,
        )
        early = service.closeout_readiness(
            award_id,
            as_of="2026-06-30",
        )
        self.assertFalse(early["ready_to_close"])
        self.assertIn("has not ended", " | ".join(early["blockers"]))

        service.set_report_status(
            award_id=award_id,
            report_id=report["report_id"],
            status="SUBMITTED",
            actor="reviewer@test",
            evidence_reference="portal:final-report",
        )
        service.set_compliance_task_status(
            award_id=award_id,
            task_id=task["task_id"],
            status="DONE",
            actor="reviewer@test",
            evidence_note="Inventory reconciled and certified",
            evidence_reference="property-inventory:final",
        )
        ready = service.closeout_readiness(
            award_id,
            as_of="2027-02-01",
        )
        self.assertTrue(ready["ready_to_close"])
        closed = service.close_award(
            award_id=award_id,
            actor="authorized@test",
            as_of="2027-02-01",
        )
        self.assertEqual(closed["status"], "CLOSED")
        with self.assertRaisesRegex(ValueError, "immutable"):
            service.add_expenditure(
                award_id=award_id,
                transaction_date="2026-12-01",
                category="Personnel",
                amount=100,
                description="Late posting",
                source_reference="ledger:late",
                actor="finance@test",
            )
        events = service.list_events(award_id)
        self.assertTrue(any(item["event_type"] == "AWARD_CLOSED" for item in events))


if __name__ == "__main__":
    unittest.main()
