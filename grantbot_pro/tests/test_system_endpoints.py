from fastapi.testclient import TestClient

from grantbot import __app_name__, __organization__, __version__
from grantbot.app import app


def test_root_identity_endpoint() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "name": __app_name__,
        "organization": __organization__,
        "version": __version__,
        "status": "active",
        "docs": "/docs",
        "health": "/health",
    }


def test_health_endpoint() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == __app_name__
    assert payload["version"] == __version__
