from __future__ import annotations

from grantbot.writing.quality_gate import evaluate_draft


def _facts() -> list[dict[str, str]]:
    return [
        {
            "status": "VERIFIED",
            "category": "program",
            "key": "workforce",
            "value": "Broken Growth Ministries provides workforce development and job-placement support.",
        },
        {
            "status": "APPROVED",
            "category": "program",
            "key": "housing",
            "value": "The program combines transitional housing with stabilization and employment support.",
        },
    ]


def test_quality_gate_rejects_unsupported_numbers() -> None:
    result = evaluate_draft(
        question="How will the program improve employment outcomes?",
        draft=(
            "Broken Growth Ministries combines workforce development, job-placement support, and "
            "transitional housing so participants can move toward stable employment. The program "
            "will achieve a 92% employment rate through individualized planning and employer support."
        ),
        facts=_facts(),
    )
    assert not result.passed
    assert "92%" in result.unsupported_numbers


def test_quality_gate_rejects_extremely_brief_answer() -> None:
    result = evaluate_draft(
        question="How will the program provide workforce development and employment support?",
        draft="We provide employment support.",
        facts=_facts(),
    )
    assert not result.passed
    assert any("too brief" in issue.lower() for issue in result.issues)


def test_quality_gate_penalizes_off_question_answer() -> None:
    result = evaluate_draft(
        question="How will participants receive workforce development, job training, and employment support?",
        draft=(
            "The organization is committed to building a supportive community grounded in dignity, "
            "personal growth, safe relationships, and long-term stability. Participants will be treated "
            "with respect and encouraged to become active members of the surrounding community."
        ),
        facts=_facts(),
    )
    assert not result.passed
    assert any("question" in issue.lower() for issue in result.issues)


def test_quality_gate_accepts_specific_supported_answer() -> None:
    result = evaluate_draft(
        question="How will the program provide workforce development and employment support?",
        draft=(
            "Broken Growth Ministries will connect transitional housing and stabilization with workforce "
            "development and job-placement support. Participants will receive structured employment support "
            "as they move from initial stabilization toward work and greater independence. The program will "
            "track employment-related progress and use documented participant information to evaluate whether "
            "services are helping residents move toward stable employment without claiming outcomes that have "
            "not yet been demonstrated."
        ),
        facts=_facts(),
    )
    assert result.passed
    assert result.score >= 80


def test_quality_gate_does_not_treat_trailing_comma_as_number() -> None:
    result = evaluate_draft(
        question="Describe the organization's incorporation date and leadership.",
        draft=(
            "The organization was incorporated on February 23, 2026. Its leadership and governance "
            "structure support responsible program development, documented oversight, and human review "
            "of legal, financial, property, and submission decisions."
        ),
        facts=[
            {
                "status": "VERIFIED",
                "key": "date_incorporated",
                "value": "2026-02-23",
            }
        ],
    )
    assert "23," not in result.unsupported_numbers
