from __future__ import annotations

from pathlib import Path

import pytest

from grantbot.crew_ai.research_tools import _source_quality, _validate_public_url, tools_for_research_agent


def test_private_networks_are_blocked() -> None:
    with pytest.raises(ValueError):
        _validate_public_url("http://127.0.0.1/private")
    with pytest.raises(ValueError):
        _validate_public_url("http://localhost/private")


def test_nonstandard_ports_are_blocked() -> None:
    with pytest.raises(ValueError):
        _validate_public_url("https://example.com:8443/data")


def test_government_sources_receive_primary_classification() -> None:
    score, source_class = _source_quality("https://www.hud.gov/program")
    assert score == 100
    assert source_class == "GOVERNMENT_PRIMARY"


def test_research_agents_have_expected_tools() -> None:
    scout = {tool.name for tool in tools_for_research_agent("funding_scout")}
    funder = {tool.name for tool in tools_for_research_agent("funder_intelligence_analyst")}
    evidence = {tool.name for tool in tools_for_research_agent("evidence_researcher")}
    knowledge = {tool.name for tool in tools_for_research_agent("knowledge_archivist")}

    assert scout == {"grants_gov_search", "public_web_search", "safe_source_fetch"}
    assert funder == {"public_web_search", "safe_source_fetch"}
    assert evidence == {"public_web_search", "safe_source_fetch"}
    assert knowledge == {"verified_knowledge_search"}


def test_no_openai_dependency_in_research_code() -> None:
    root = Path(__file__).resolve().parents[1] / "grantbot" / "crew_ai"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "OPENAI_API_KEY" not in text
    assert "openai/" not in text.lower()
