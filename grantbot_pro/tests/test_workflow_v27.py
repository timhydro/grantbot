from __future__ import annotations

import os
from pathlib import Path

import pytest

from grantbot.app import app
from grantbot.workflow import control_plane_v27 as workflow


def test_v27_routes_are_registered() -> None:
    paths = set(app.openapi()["paths"])
    assert "/v27/workflow/health" in paths
    assert "/v27/workflow/runs" in paths
    assert "/v27/workflow/runs/{run_id}" in paths
    assert "/v27/workflow/runs/{run_id}/advance" in paths
    assert "/v27/workflow/runs/{run_id}/sync" in paths
    assert "/v27/workflow/runs/{run_id}/execution" in paths


def test_v27_schema_is_persistent_and_human_gated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "workflow.db"
    monkeypatch.setenv("GRANTBOT_DB_PATH", str(db))
    workflow.initialize_schema()
    status = workflow.health()
    assert status["healthy"] is True
    assert status["persistent"] is True
    assert status["resumable"] is True
    assert status["human_approval_required"] is True
    assert status["submission_enabled"] is False
    assert db.exists()


def test_v27_state_derivation_never_auto_submits() -> None:
    assert workflow._derive_state({"stage": "DRAFTING", "risks": [], "checklist": []}) == "ACTIVE"
    assert workflow._derive_state({"stage": "READY_FOR_REVIEW", "risks": [], "checklist": []}) == "WAITING_FOR_HUMAN_REVIEW"
    assert workflow._derive_state({"stage": "READY_FOR_SUBMISSION", "risks": [], "checklist": []}) == "READY_FOR_SUBMISSION"
    assert workflow._derive_state({"stage": "DRAFTING", "risks": [{"status": "OPEN"}], "checklist": []}) == "WAITING_FOR_USER"
    assert workflow._derive_state({"stage": "DRAFTING", "risks": [], "checklist": [{"status": "PENDING"}]}) == "WAITING_FOR_USER"
