from __future__ import annotations

import unittest
from unittest.mock import patch

from grantbot import __version__
from grantbot.agents.crewai_runtime import CrewRuntime
from grantbot.agents.crewai_single_voice import (
    ROLE_ORDER,
    _deterministic_checks,
    build_single_voice_crew,
)
from grantbot.app import app
from grantbot.writing.voice_contract import render_voice_contract, voice_integrity_issues


class DummyAgent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class DummyTask:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class DummyCrew:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class DummyProcess:
    sequential = "sequential"


class ProductionV29Tests(unittest.TestCase):
    def _plan(self) -> dict[str, CrewRuntime]:
        return {
            role: CrewRuntime(
                available=True,
                provider="test",
                model=f"test/{role}",
                base_url=None,
                mode="test",
            )
            for role in ROLE_ORDER
        }

    def test_version_is_v29(self) -> None:
        self.assertEqual(__version__, "29.0.0")

    def test_voice_contract_requires_single_author(self) -> None:
        contract = render_voice_contract().lower()
        self.assertIn("sole author", contract)
        self.assertIn("same organizational voice", contract)

    def test_voice_gate_blocks_internal_orchestration_language(self) -> None:
        issues = voice_integrity_issues(
            "CrewAI and the Grant Quality Reviewer prepared this response."
        )
        self.assertTrue(issues)

    def test_master_writer_is_reused_for_revision(self) -> None:
        fake_loader = lambda: (DummyAgent, DummyCrew, DummyProcess, DummyTask)
        with patch(
            "grantbot.agents.crewai_single_voice._load_crewai",
            side_effect=fake_loader,
        ), patch(
            "grantbot.agents.crewai_single_voice.resolve_single_voice_plan",
            return_value=self._plan(),
        ), patch(
            "grantbot.agents.crewai_single_voice._build_llm",
            side_effect=lambda runtime: object(),
        ), patch(
            "grantbot.agents.crewai_single_voice._style_memory",
            return_value="(none)",
        ):
            _, crew = build_single_voice_crew(question="Describe the program.")

        draft_task = crew.tasks[3]
        review_task = crew.tasks[4]
        revision_task = crew.tasks[5]
        readiness_task = crew.tasks[6]

        self.assertIs(draft_task.agent, revision_task.agent)
        self.assertIsNot(review_task.agent, draft_task.agent)
        self.assertIsNot(readiness_task.agent, draft_task.agent)
        self.assertEqual(draft_task.agent.role, "Broken Growth Master Grant Writer")
        self.assertEqual(
            review_task.agent.role,
            "Independent Grant Quality and Compliance Reviewer",
        )
        self.assertNotIn("rewrite", review_task.expected_output.lower())
        self.assertIn("no applicant-facing prose", readiness_task.expected_output.lower())

    def test_deterministic_gates_accept_supported_single_voice_answer(self) -> None:
        facts = [
            {
                "fact_id": "fact-1",
                "fact_key": "program_model",
                "category": "program",
                "value": "Broken Growth provides housing and workforce support for participants.",
                "verification_state": "VERIFIED",
                "source": "board-approved program record",
            }
        ]
        quality, claims, voice = _deterministic_checks(
            question="Describe the housing and workforce support program.",
            final_answer="Broken Growth provides housing and workforce support for participants.",
            facts=facts,
            dossier="The application requests a description of housing and workforce support.",
            max_words=100,
        )
        self.assertTrue(quality["passed"])
        self.assertTrue(claims["safe"])
        self.assertTrue(voice["passed"])

    def test_production_routes_are_authenticated(self) -> None:
        schema = app.openapi()
        for path, method in (
            ("/v29/production/status", "get"),
            ("/v29/production/answer", "post"),
            ("/v29/production/irs1023/build", "post"),
        ):
            operation = schema["paths"][path][method]
            self.assertTrue(operation.get("security"), path)


if __name__ == "__main__":
    unittest.main()
