from __future__ import annotations

from grantbot.app import app


def test_local_ai_health_route_is_registered() -> None:
    paths = set(app.openapi().get("paths", {}))
    assert "/v21/local-ai/health" in paths
