from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from grantbot.matching.competitive_v14 import (
    analyze_competitiveness,
)
from grantbot.nofo.acquisition_v13 import (
    acquire_blueprint,
    load_blueprint,
)


NUMBER_RE = re.compile(
    r"(?<![A-Za-z])(?:\$?\d[\d,]*(?:\.\d+)?%?)(?![A-Za-z])"
)


@dataclass(frozen=True, slots=True)
class ComplianceReadiness:
    opportunity_id: str
    competitive_score: int
    compliance_score: int
    budget_score: int
    outcomes_score: int
    final_readiness_score: int
    status: str
    missing_items: list[str]
    compliance_risks: list[str]
    budget_requirements: list[str]
    outcome_requirements: list[str]
    required_attachments: list[str]
    submission_requirements: list[str]
    output_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _status(score: int, risks: list[str]) -> str:
    if any(
        "REJECT" in risk.upper()
        for risk in risks
    ):
        return "REJECTED"

    if score >= 90:
        return "SUBMISSION_READY"

    if score >= 75:
        return "NEAR_READY"

    if score >= 55:
        return "REVISION_REQUIRED"

    return "NOT_READY"


def evaluate_readiness(
    opportunity_id: str,
) -> ComplianceReadiness:
    competitive = analyze_competitiveness(
        opportunity_id,
        acquire_if_missing=True,
    )

    try:
        blueprint = load_blueprint(opportunity_id)
    except FileNotFoundError:
        blueprint = acquire_blueprint(
            opportunity_id
        ).to_dict()

    missing: list[str] = []
    risks: list[str] = []

    questions = blueprint.get("application_questions", [])
    requirements = blueprint.get("requirements", [])
    budgets = blueprint.get("budget_requirements", [])
    matches = blueprint.get("match_requirements", [])
    attachments = blueprint.get("required_attachments", [])
    submissions = blueprint.get("submission_requirements", [])

    if competitive.priority == "REJECT":
        risks.append(
            "REJECT: opportunity failed competitive/eligibility gate."
        )

    if not questions:
        missing.append(
            "Complete application-question set"
        )

    if not requirements:
        missing.append(
            "Complete application-requirement set"
        )

    if not budgets:
        missing.append(
            "Budget instructions"
        )

    if not submissions:
        missing.append(
            "Submission instructions"
        )

    compliance_score = 100

    if missing:
        compliance_score -= min(
            60,
            len(missing) * 15,
        )

    if competitive.applicant_role.get("verification_required"):
        compliance_score -= 15
        risks.append(
            "Applicant eligibility still requires verification."
        )

    budget_score = 100

    if not budgets:
        budget_score -= 35

    if matches:
        budget_score -= 15
        risks.append(
            "Match/cost-sharing requirements require a verified financing plan."
        )

    outcomes_requirements = [
        line
        for line in requirements
        if any(
            term in line.lower()
            for term in (
                "outcome",
                "performance",
                "measure",
                "evaluation",
                "data collection",
                "reporting",
            )
        )
    ]

    outcomes_score = 100

    if not outcomes_requirements:
        outcomes_score -= 25
        missing.append(
            "Outcome/performance-measure requirements"
        )

    final_score = round(
        competitive.final_score * 0.35
        + compliance_score * 0.30
        + budget_score * 0.20
        + outcomes_score * 0.15
    )

    acquisition_status = str(blueprint.get("acquisition_status", "")).upper()
    q_noise = sum(1 for q in questions if any(x in str(q).lower() for x in ("balance of state coc", "can you talk about", "questions?", "questions or comments?", "find state resources")))
    bad_attachments = [a for a in attachments if not any(x in str(a).lower() for x in ("attachment", "form", "sf-", "budget", "resume", "letter", "certification", "agreement", "documentation"))]
    if acquisition_status != "FULL_NOFO_VALIDATED":
        risks.append("NOFO text acquired, but authoritative extraction has not been fully validated.")
        final_score = min(final_score, 74)
    if questions and q_noise >= max(3, len(questions) // 3):
        risks.append("Application-question extraction failed quality validation.")
        missing.append("Verified application-question set")
        final_score = min(final_score, 54)
    if attachments and len(bad_attachments) == len(attachments):
        risks.append("Required-attachment extraction failed quality validation.")
        missing.append("Verified required-attachment list")
        final_score = min(final_score, 54)

    final_score = max(
        0,
        min(100, final_score),
    )

    status = _status(
        final_score,
        risks,
    )

    root = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "compliance"
        / str(opportunity_id)
    )
    root.mkdir(parents=True, exist_ok=True)

    output_path = root / "readiness_v15.json"

    result = ComplianceReadiness(
        opportunity_id=str(opportunity_id),
        competitive_score=competitive.final_score,
        compliance_score=max(0, compliance_score),
        budget_score=max(0, budget_score),
        outcomes_score=max(0, outcomes_score),
        final_readiness_score=final_score,
        status=status,
        missing_items=list(dict.fromkeys(missing)),
        compliance_risks=list(dict.fromkeys(risks)),
        budget_requirements=budgets,
        outcome_requirements=outcomes_requirements,
        required_attachments=attachments,
        submission_requirements=submissions,
        output_path=str(output_path),
    )

    output_path.write_text(
        json.dumps(
            result.to_dict(),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    return result
