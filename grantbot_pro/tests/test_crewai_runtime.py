from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grantbot.agents.crewai_flow import GrantFlowState
from grantbot.agents.crewai_runtime import (
    ORCHESTRATION_MODE,
    CrewRuntime,
    _readiness_status,
    _select_runtime,
    _stage_result,
)
from grantbot.api.agentic_v26 import CrewRequest
from grantbot.app import app


class CrewAIRuntimeTests(unittest.TestCase):
    def test_openrouter_free_is_preferred_automatically(self) -> None:
        runtime = _select_runtime(
            environment={"OPENROUTER_API_KEY": "test-key"},
            local_health={"available": False},
        )
        self.assertTrue(runtime.available)
        self.assertEqual(runtime.provider, "openrouter")
        self.assertEqual(runtime.model, "openrouter/openrouter/free")
        self.assertEqual(runtime.mode, "automatic-free-cloud")

    def test_metered_groq_is_not_used_without_opt_in(self) -> None:
        runtime = _select_runtime(
            environment={"GROQ_API_KEY": "test-key"},
            local_health={"available": False},
        )
        self.assertFalse(runtime.available)
        self.assertEqual(runtime.provider, "none")

    def test_metered_groq_requires_explicit_opt_in(self) -> None:
        runtime = _select_runtime(
            environment={
                "GROQ_API_KEY": "test-key",
                "GRANTBOT_ALLOW_METERED_AI": "1",
            },
            local_health={"available": False},
        )
        self.assertTrue(runtime.available)
        self.assertEqual(runtime.provider, "groq")
        self.assertEqual(runtime.model, "groq/openai/gpt-oss-120b")

    def test_real_ollama_health_shape_is_accepted(self) -> None:
        runtime = _select_runtime(
            environment={},
            local_health={
                "available": True,
                "configured_model": "llama3.2:3b",
                "selected_model": "llama3.2:3b",
                "installed_models": ["llama3.2:3b", "nomic-embed-text:latest"],
            },
        )
        self.assertTrue(runtime.available)
        self.assertEqual(runtime.provider, "ollama")
        self.assertEqual(runtime.model, "ollama/llama3.2:3b")
        self.assertEqual(runtime.mode, "automatic-local")

    def test_explicit_ollama_model_must_be_installed(self) -> None:
        runtime = _select_runtime(
            environment={},
            local_health={
                "available": True,
                "selected_model": "llama3.2:3b",
                "installed_models": ["llama3.2:3b"],
            },
            model_override="ollama/missing-model:latest",
        )
        self.assertFalse(runtime.available)
        self.assertIn("not installed", runtime.reason or "")

    def test_explicit_cloud_model_requires_matching_key(self) -> None:
        runtime = _select_runtime(
            environment={"GRANTBOT_ALLOW_METERED_AI": "1"},
            local_health={},
            model_override="groq/openai/gpt-oss-120b",
        )
        self.assertFalse(runtime.available)
        self.assertIn("GROQ_API_KEY", runtime.reason or "")

    def test_explicit_paid_cloud_model_still_requires_metered_opt_in(self) -> None:
        runtime = _select_runtime(
            environment={"GROQ_API_KEY": "test-key"},
            local_health={},
            model_override="groq/openai/gpt-oss-120b",
        )
        self.assertFalse(runtime.available)
        self.assertIn("Metered CrewAI models are disabled", runtime.reason or "")

    def test_unknown_provider_is_rejected(self) -> None:
        runtime = _select_runtime(
            environment={"GRANTBOT_ALLOW_METERED_AI": "1"},
            local_health={},
            model_override="untrusted/model",
        )
        self.assertFalse(runtime.available)
        self.assertIn("Unsupported CrewAI provider", runtime.reason or "")

    def test_remote_ollama_is_blocked_by_default(self) -> None:
        runtime = _select_runtime(
            environment={"GRANTBOT_CREWAI_OLLAMA_URL": "http://10.0.0.5:11434"},
            local_health={
                "available": True,
                "selected_model": "llama3.2:3b",
                "installed_models": ["llama3.2:3b"],
            },
        )
        self.assertFalse(runtime.available)
        self.assertIn("Remote Ollama is disabled", runtime.reason or "")

    def test_caller_cannot_supply_base_url(self) -> None:
        self.assertNotIn("base_url", CrewRequest.model_fields)

    def test_crew_api_requires_authentication(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/v26/agents/crew"]["post"]
        self.assertTrue(operation.get("security"))

    def test_flow_state_is_always_human_gated(self) -> None:
        state = GrantFlowState()
        self.assertTrue(state.human_review_required)
        self.assertFalse(state.submission_performed)
        self.assertFalse(state.safe_to_submit)

    def test_readiness_parser_is_fail_closed(self) -> None:
        self.assertEqual(
            _readiness_status("READINESS=READY_FOR_HUMAN_REVIEW\nAll AI checks complete."),
            "READY_FOR_HUMAN_REVIEW",
        )
        self.assertEqual(
            _readiness_status("PASS_FOR_STAGING\nLegacy wording."),
            "REMEDIATION_REQUIRED",
        )
        self.assertEqual(_readiness_status(""), "REMEDIATION_REQUIRED")

    def test_staging_receipt_is_real_and_submission_remains_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = CrewRuntime(
                available=True,
                provider="openrouter",
                model="openrouter/openrouter/free",
                base_url=None,
                mode="test",
            )
            path, receipt = _stage_result(
                runtime=runtime,
                dossier="verified dossier",
                question="Describe the program.",
                max_words=500,
                output="READINESS=READY_FOR_HUMAN_REVIEW\nReviewed output.",
                staging_dir=Path(temp),
            )
            destination = Path(path)
            self.assertTrue(destination.is_file())
            self.assertEqual(len(receipt), 64)
            data = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "READY_FOR_HUMAN_REVIEW")
            self.assertEqual(data["orchestration"], ORCHESTRATION_MODE)
            self.assertEqual(data["agent_count"], 6)
            self.assertTrue(data["human_review_required"])
            self.assertFalse(data["submission_performed"])
            self.assertFalse(data["safe_to_submit"])
            self.assertFalse(data["external_side_effects_performed"])


if __name__ == "__main__":
    unittest.main()
