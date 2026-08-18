from __future__ import annotations

from pathlib import Path


def test_v21_shell_scripts_exist_and_reference_expected_entrypoints() -> None:
    root = Path(__file__).resolve().parents[1]
    bootstrap = (root / "bootstrap.sh").read_text(encoding="utf-8")
    setup_ai = (root / "setup_local_ai.sh").read_text(encoding="utf-8")
    runner = (root / "run_grantbot.sh").read_text(encoding="utf-8")

    assert "--with-local-ai" in bootstrap
    assert "setup_local_ai.sh" in bootstrap
    assert "python -m pytest -q" in bootstrap or "python -m pytest" in bootstrap
    assert "ollama pull" in setup_ai
    assert "/api/tags" in setup_ai
    assert "uvicorn grantbot.app:app" in runner
    assert "openapi.json" in runner
