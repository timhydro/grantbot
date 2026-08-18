from __future__ import annotations

from grantbot.writing.ollama_provider import OllamaConfig, OllamaProvider


def test_local_ai_health_reports_unavailable_without_crashing(monkeypatch) -> None:
    provider = OllamaProvider(OllamaConfig(model="local:test"))

    def fail() -> list[str]:
        raise RuntimeError("offline")

    monkeypatch.setattr(provider, "installed_models", fail)
    health = provider.health()
    assert health["available"] is False
    assert health["configured_model"] == "local:test"
    assert health["selected_model"] is None
    assert "offline" in health["error"]
