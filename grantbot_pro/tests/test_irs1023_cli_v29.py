from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from grantbot.production import irs1023_cli


def test_load_project_environment_uses_explicit_dotenv_path(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("EXAMPLE_KEY=value\n", encoding="utf-8")

    with patch.object(irs1023_cli, "ENV_PATH", env_path), patch(
        "grantbot.production.irs1023_cli.load_dotenv"
    ) as loader:
        returned = irs1023_cli.load_project_environment()

    assert returned == env_path
    loader.assert_called_once_with(dotenv_path=env_path, override=False)


def test_load_project_environment_skips_missing_file(tmp_path: Path) -> None:
    env_path = tmp_path / "missing.env"

    with patch.object(irs1023_cli, "ENV_PATH", env_path), patch(
        "grantbot.production.irs1023_cli.load_dotenv"
    ) as loader:
        returned = irs1023_cli.load_project_environment()

    assert returned == env_path
    loader.assert_not_called()


def test_model_plan_counts_distinct_model_identities() -> None:
    status = {
        "production_pipeline": {
            "available": True,
            "master_writer_reused_for_revision": True,
            "reviewer_can_rewrite_final_prose": False,
            "readiness_can_rewrite_final_prose": False,
            "human_review_required": True,
            "roles": {
                "research": {
                    "available": True,
                    "provider": "groq",
                    "model": "groq/model-a",
                },
                "writing": {
                    "available": True,
                    "provider": "gemini",
                    "model": "gemini/model-b",
                },
            },
        }
    }

    available, identities = irs1023_cli._print_model_plan(status)

    assert available is True
    assert identities == 2
