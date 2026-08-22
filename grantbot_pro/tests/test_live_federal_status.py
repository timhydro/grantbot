from __future__ import annotations

import unittest
from datetime import date

from grantbot.discovery.status_guard import (
    OpportunityState,
    evaluate_opportunity_status,
    scan_authority_text,
)


class StatusGuardTests(unittest.TestCase):

    def test_vacated_notice_is_invalidating(self) -> None:
        text = (
            "FY 2026 Continuum of Care Competition. "
            "Notice of Court Order. The court determined the 2026 CoC NOFO "
            "violated the Administrative Procedure Act and vacated it. "
            "The application deadline is no longer in force and HUD is "
            "unable to accept applications at this time."
        )

        result = scan_authority_text(
            text,
            ["FY 2026 Continuum of Care Competition"],
        )

        self.assertIn(
            "VACATED",
            result["invalidating_flags"],
        )
        self.assertIn(
            "UNABLE_TO_ACCEPT_APPLICATIONS",
            result["invalidating_flags"],
        )

    def test_unrelated_vacated_text_is_ignored(self) -> None:
        text = (
            "Program Alpha remains open. "
            + ("safe text " * 500)
            + "A completely different program was vacated."
        )

        result = scan_authority_text(
            text,
            ["Program Alpha"],
        )

        self.assertEqual(
            result["invalidating_flags"],
            [],
        )

    def test_modified_notice_is_advisory_not_invalidating(self) -> None:
        text = (
            "Program Alpha NOFO. Notice of Modified NOFO. "
            "The agency amended the funding notice."
        )

        result = scan_authority_text(
            text,
            ["Program Alpha NOFO"],
        )

        self.assertEqual(
            result["invalidating_flags"],
            [],
        )
        self.assertIn(
            "MODIFIED",
            result["revision_flags"],
        )
        self.assertIn(
            "AMENDED",
            result["revision_flags"],
        )

    def test_past_deadline_closes_opportunity(self) -> None:
        decision = evaluate_opportunity_status(
            hit={
                "number": "TEST-1",
                "title": "Test",
                "oppStatus": "posted",
                "closeDate": "08/01/2026",
            },
            detail={},
            verify_authority=False,
            today=date(2026, 8, 21),
        )

        self.assertEqual(
            decision.state,
            OpportunityState.CLOSED.value,
        )
        self.assertFalse(decision.drafting_allowed)
        self.assertFalse(decision.submission_allowed)

    def test_posted_future_opportunity_is_active(self) -> None:
        decision = evaluate_opportunity_status(
            hit={
                "number": "TEST-2",
                "title": "Test",
                "oppStatus": "posted",
                "closeDate": "12/01/2026",
            },
            detail={},
            verify_authority=False,
            today=date(2026, 8, 21),
        )

        self.assertEqual(
            decision.state,
            OpportunityState.ACTIVE.value,
        )
        self.assertTrue(decision.drafting_allowed)
        self.assertFalse(decision.submission_allowed)

    def test_forecasted_is_planning_only(self) -> None:
        decision = evaluate_opportunity_status(
            hit={
                "number": "TEST-3",
                "title": "Test",
                "oppStatus": "forecasted",
                "closeDate": "",
            },
            detail={},
            verify_authority=False,
            today=date(2026, 8, 21),
        )

        self.assertEqual(
            decision.state,
            OpportunityState.FORECASTED.value,
        )
        self.assertTrue(decision.drafting_allowed)
        self.assertFalse(decision.submission_allowed)


if __name__ == "__main__":
    unittest.main()
