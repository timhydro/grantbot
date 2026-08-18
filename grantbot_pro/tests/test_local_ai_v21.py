from __future__ import annotations

from types import SimpleNamespace

import pytest

from grantbot.writing.master_writer import write_answer
from grantbot.writing.ollama_provider import OllamaConfig, OllamaProvider


def test_ollama_selects_configured_model_when_installed() -> None:
    provider = OllamaProvider(
        OllamaConfig(
            model="preferred:3b",
            fallback_models=("fallback:latest",),
            allow_any_installed=True,
        )
    )
    selected = provider.select_model(["other:latest", "preferred:3b"])
    assert selected == "preferred:3b"


def test_ollama_uses_configured_fallback_before_arbitrary_model() -> None:
    provider = OllamaProvider(
        OllamaConfig(
            model="missing:3b",
            fallback_models=("fallback:latest",),
            allow_any_installed=True,
        )
    )
    selected = provider.select_model(["other:latest", "fallback:latest"])
    assert selected == "fallback:latest"


def test_ollama_can_fall_back_to_any_installed_local_model() -> None:
    provider = OllamaProvider(
        OllamaConfig(
            model="missing:3b",
            fallback_models=(),
            allow_any_installed=True,
        )
    )
    assert provider.select_model(["available:latest"]) == "available:latest"


def test_ollama_refuses_missing_model_when_fallback_disabled() -> None:
    provider = OllamaProvider(
        OllamaConfig(
            model="missing:3b",
            fallback_models=(),
            allow_any_installed=False,
        )
    )
    with pytest.raises(RuntimeError, match="No usable local Ollama model"):
        provider.select_model(["other:latest"])


class FakeProvider:
    def __init__(self) -> None:
        self.config = SimpleNamespace(model="test-local:latest")
        self.last_model = ""
        self.calls = 0

    def generate(
        self,
        prompt: str,
        *,
        system: str,
        temperature: float = 0.3,
    ) -> str:
        assert prompt.strip()
        assert system.strip()
        assert 0 <= temperature <= 1
        self.calls += 1
        self.last_model = "test-local:latest"
        if self.calls == 1:
            return "The program design will serve 42 people through housing and workforce support."
        return (
            "The program design provides housing and workforce support for adults "
            "returning from incarceration, using the verified service population as "
            "the basis for implementation."
        )


def test_writer_automatically_revises_quality_gate_failure() -> None:
    provider = FakeProvider()
    result = write_answer(
        question="Describe the program design.",
        section="program_design",
        facts=[
            {
                "id": "population",
                "category": "program",
                "key": "population",
                "value": "adults returning from incarceration",
                "status": "VERIFIED",
                "source": "test",
            }
        ],
        provider=provider,
    )
    assert provider.calls == 2
    assert result.revision_attempts == 1
    assert result.status == "READY_FOR_HUMAN_REVIEW"
    assert result.model == "test-local:latest"
    assert result.quality is not None
    assert result.quality["passed"] is True
    assert "42" not in (result.draft or "")


def test_writer_does_not_call_model_without_usable_facts() -> None:
    provider = FakeProvider()
    result = write_answer(
        question="Describe the program design.",
        section="program_design",
        facts=[
            {
                "id": "missing",
                "category": "program",
                "key": "missing_item",
                "value": None,
                "status": "MISSING",
                "source": "test",
            }
        ],
        provider=provider,
    )
    assert provider.calls == 0
    assert result.status == "MISSING_INFORMATION"
    assert result.draft is None
