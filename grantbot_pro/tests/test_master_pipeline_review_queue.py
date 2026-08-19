from fastapi.testclient import TestClient

from grantbot.app import app


def test_analyze_creates_review_folder_for_high_score_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANTBOT_APPLICATION_ROOT", str(tmp_path))
    client = TestClient(app)

    payload = {
        "opportunities": [
            {
                "id": "faith-grant-1",
                "title": "Faith-Based Reentry Housing Grant",
                "funder": "Example Foundation",
                "description": "Funding for homelessness, supportive housing, reentry, and workforce development.",
                "eligibility": "A church or other faith-based organization may apply.",
                "amount": 5000,
                "source_url": "https://example.org/grant"
            }
        ],
        "generate_drafts": False,
        "create_review_folders": True,
        "minimum_review_score": 0,
        "applicant_tax_status": "pending_501c3",
        "has_fiscal_sponsor": False
    }

    response = client.post("/v5/opportunities/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["review_folders_created"] == 1
    assert data["review_folders"][0]["opportunity_id"] == "faith-grant-1"
    assert (tmp_path / "faith-grant-1" / "application.json").exists()
    assert (tmp_path / "faith-grant-1" / "REVIEW.md").exists()
    assert (tmp_path / "faith-grant-1" / "STATUS.json").exists()


def test_review_folder_creation_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANTBOT_APPLICATION_ROOT", str(tmp_path))
    client = TestClient(app)
    payload = {
        "opportunities": [
            {
                "id": "disabled-1",
                "title": "Housing Grant",
                "description": "Supportive housing and homelessness assistance.",
                "eligibility": "501(c)(3) not required",
                "source_url": "https://example.org"
            }
        ],
        "generate_drafts": False,
        "create_review_folders": False,
        "minimum_review_score": 0
    }
    response = client.post("/v5/opportunities/analyze", json=payload)
    assert response.status_code == 200
    assert response.json()["review_folders_created"] == 0
    assert not (tmp_path / "disabled-1").exists()
