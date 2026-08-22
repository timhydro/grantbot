from __future__ import annotations

import unittest

from grantbot.applications.irs1023 import CORE_QUESTIONS, detect_schedule_flags


class IRS1023V28Tests(unittest.TestCase):
    def test_core_questions_cover_required_narrative_parts(self) -> None:
        parts = {question.part for question in CORE_QUESTIONS}
        self.assertIn("Part IV", parts)
        self.assertIn("Part V", parts)
        self.assertIn("Part VI", parts)
        self.assertIn("Part VII", parts)
        self.assertIn("Part VIII", parts)
        self.assertIn("Part IX", parts)

    def test_housing_program_flags_schedule_f_for_human_review(self) -> None:
        flags = detect_schedule_flags(
            [
                {
                    "fact_key": "housing_program",
                    "category": "program",
                    "value": "Transitional tiny-home supportive housing",
                    "verification_state": "APPROVED",
                }
            ]
        )
        self.assertEqual(flags["F"], "POTENTIALLY_REQUIRED")

    def test_faith_based_language_does_not_automatically_classify_as_church(self) -> None:
        flags = detect_schedule_flags(
            [
                {
                    "fact_key": "faith_based",
                    "category": "organization",
                    "value": "Christian faith-centered ministry",
                    "verification_state": "APPROVED",
                }
            ]
        )
        self.assertEqual(flags["A"], "NOT_INDICATED")

    def test_submission_is_not_part_of_question_catalog(self) -> None:
        combined = " ".join(question.prompt.lower() for question in CORE_QUESTIONS)
        self.assertNotIn("automatically submit", combined)


if __name__ == "__main__":
    unittest.main()
