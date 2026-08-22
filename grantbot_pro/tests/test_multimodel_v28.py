from __future__ import annotations

import unittest

from grantbot.agents.crewai_multimodel import (
    _candidate_models,
    extract_final_answer,
)


class MultiModelV28Tests(unittest.TestCase):
    def test_writer_prefers_xai_when_metered_and_configured(self) -> None:
        candidates = _candidate_models(
            "writing",
            {
                "GRANTBOT_ALLOW_METERED_AI": "1",
                "XAI_API_KEY": "x",
                "GRANTBOT_XAI_MODEL": "xai/grok-4",
                "GEMINI_API_KEY": "g",
                "MISTRAL_API_KEY": "m",
            },
        )
        self.assertEqual(candidates[0], "xai/grok-4")
        self.assertIn("mistral/mistral-large-latest", candidates)
        self.assertIn("gemini/gemini-2.5-flash", candidates)

    def test_compliance_prefers_gemini_when_metered(self) -> None:
        candidates = _candidate_models(
            "eligibility",
            {
                "GRANTBOT_ALLOW_METERED_AI": "true",
                "GEMINI_API_KEY": "g",
                "GROQ_API_KEY": "q",
            },
        )
        self.assertEqual(candidates[0], "gemini/gemini-2.5-flash")

    def test_metered_models_are_not_selected_without_opt_in(self) -> None:
        candidates = _candidate_models(
            "writing",
            {
                "XAI_API_KEY": "x",
                "GRANTBOT_XAI_MODEL": "xai/grok-4",
                "GEMINI_API_KEY": "g",
                "OPENROUTER_API_KEY": "o",
            },
        )
        self.assertEqual(candidates, ["openrouter/openrouter/free"])

    def test_explicit_role_model_overrides_automatic_plan(self) -> None:
        candidates = _candidate_models(
            "writing",
            {
                "GRANTBOT_CREWAI_WRITING_MODEL": "gemini/gemini-2.5-flash",
                "GRANTBOT_ALLOW_METERED_AI": "1",
                "XAI_API_KEY": "x",
                "GRANTBOT_XAI_MODEL": "xai/grok-4",
            },
        )
        self.assertEqual(candidates, ["gemini/gemini-2.5-flash"])

    def test_final_answer_parser_is_fail_closed(self) -> None:
        output = (
            "READINESS=READY_FOR_HUMAN_REVIEW\n"
            "FINAL_ANSWER_BEGIN\n"
            "Supported final answer.\n"
            "FINAL_ANSWER_END\n"
            "Human review required."
        )
        self.assertEqual(extract_final_answer(output), "Supported final answer.")
        self.assertIsNone(extract_final_answer("READINESS=READY_FOR_HUMAN_REVIEW"))


if __name__ == "__main__":
    unittest.main()
