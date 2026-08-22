from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grantbot.agents.crewai_runtime import (
    CrewRuntime,
    _select_runtime,
    _stage_result,
)


class CrewAIRuntimeTests(unittest.TestCase):
    def test_openrouter_free_is_preferred_automatically(self) -> None:
        runtime = _select_runtime(
            environment={"OPENROUTER_API_KEY": "test-key"},
            local_health={"available": False, "model_installed": False},
        )
        self.assertTrue(runtime.available)
        self.assertEqual(runtime.provider, "openrouter")
        self.assertEqual(runtime.model, "openrouter/openrouter/free")
        self.assertEqual(runtime.mode, "automatic-free-cloud")

    def test_metered_groq_is_not_used_without_opt_in(self) -> None:
        runtime = _select_runtime(
            environment={"GROQ_API_KEY": "test-key"},
            local_health={"available": False, "model_installed": False},
        )
        self.assertFalse(runtime.available)
        self.assertEqual(runtime.provider, "none")

    def test_metered_groq_requires_explicit_opt_in(self) -> None:
        runtime = _select_runtime(
            environment={
                "GROQ_API_KEY": "test-key",
                "GRANTBOT_ALLOW_METERED_AI": "1",
            },
            local_health={"available": False, "model_installed": False},
        )
        self.assertTrue(runtime.available)
        self.assertEqual(runtime.provider, "groq")
        self.assertEqual(runtime.model, "groq/openai/gpt-oss-120b")

    def test_local_ollama_is_supported_without_cloud_keys(self) -> None:
        runtime = _select_runtime(
            environment={},
            local_health={
                "available": True,
                "model_installed": True,
                "selected_model": "llama3.2:3b",
            },
        )
        self.assertTrue(runtime.available)
        self.assertEqual(runtime.provider, "ollama")
        self.assertEqual(runtime.model, "ollama/llama3.2:3b")

    def test_explicit_cloud_model_requires_matching_key(self) -> None:
        runtime = _select_runtime(
            environment={},
            local_health={},
            model_override="groq/openai/gpt-oss-120b",
        )
        self.assertFalse(runtime.available)
        self.assertIn("GROQ_API_KEY", runtime.reason or "")

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
                output="PASS_FOR_STAGING\nReviewed output.",
                staging_dir=Path(temp),
            )
            destination = Path(path)
            self.assertTrue(destination.is_file())
            self.assertEqual(len(receipt), 64)
            data = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "READY_FOR_HUMAN_REVIEW")
            self.assertFalse(data["submission_performed"])
            self.assertFalse(data["safe_to_submit"])
            self.assertFalse(data["external_side_effects_performed"])


if __name__ == "__main__":
    unittest.main()
