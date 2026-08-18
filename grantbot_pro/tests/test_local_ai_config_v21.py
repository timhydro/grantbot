from __future__ import annotations

from grantbot.core.config import Settings


def test_local_ai_defaults_are_local_first() -> None:
    settings = Settings()
    assert settings.ollama_enabled is True
    assert settings.ollama_model
    assert settings.ollama_url.startswith(("http://", "https://"))
