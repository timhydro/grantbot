from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from grantbot.eligibility.applicant_role import classify_applicant_role
from grantbot.nofo.acquisition_v13 import (
    acquire_blueprint,
    load_blueprint,
)
from grantbot.nofo.full_detail import get_full_nofo_intelligence


@dataclass(frozen=True, slots=True)
class CompetitiveMatch:
    opportunity_id: str
    title: str
    funder: str
    applicant_role: dict[str, Any]
    mission_fit_score: int
    readiness_score: int
    competitiveness_score: int
    burden_score: int
    final_score: int
    priority: str
    strengths: list[str]
    weaknesses: list[str]
    blockers: list[str]
    output_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _priority(score: int, blocked: bool) -> str:
    if blocked:
        return "REJECT"
    if score >= 85:
        return "CRITICAL"
    if score >= 75:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    if score >= 40:
        return "LOW"
    return "VERY_LOW"


def analyze_competitiveness(
    opportunity_id: str,
    *,
    acquire_if_missing: bool = True,
) -> CompetitiveMatch:
    full = get_full_nofo_intelligence(opportunity_id)

    role = classify_applicant_role(
        eligibility=full.eligibility,
        existing_blockers=list(
            full.eligibility_gate.get("blockers", [])
        ),
    )

    try:
        blueprint = load_blueprint(opportunity_id)
    except FileNotFoundError:
        if not acquire_if_missing:
            blueprint = {}
        else:
            blueprint = acquire_blueprint(
                opportunity_id
            ).to_dict()

    analysis = full.analysis or {}

    mission_fit = int(
        analysis.get("fit_score", 0)
        or 0
    )

    strengths: list[str] = []
    weaknesses: list[str] = []
    blockers = list(role.blockers)

    questions = blueprint.get("application_questions", [])
    requirements = blueprint.get("requirements", [])
    scoring = blueprint.get("scoring_criteria", [])
    match_requirements = blueprint.get("match_requirements", [])
    attachments = blueprint.get("required_attachments", [])

    readiness = 100

    if not questions:
        readiness -= 20
        weaknesses.append(
            "Application questions are not yet fully extracted."
        )
    else:
        strengths.append(
            "Application questions are available for writer handoff."
        )

    if not requirements:
        readiness -= 15
        weaknesses.append(
            "Application requirements are incomplete."
        )
    else:
        strengths.append(
            "Application requirements have been extracted."
        )

    if not scoring:
        readiness -= 10
        weaknesses.append(
            "Scoring/evaluation criteria are not yet available."
        )
    else:
        strengths.append(
            "Scoring criteria are available for competitive targeting."
        )

    if role.role == "DIRECT_APPLICANT":
        strengths.append(
            "Broken Growth is classified as a direct applicant."
        )
    elif role.role == "PARTNER_OR_SUBRECIPIENT":
        readiness -= 10
        weaknesses.append(
            "Opportunity requires a prime-applicant partnership strategy."
        )
    elif role.role == "VERIFY":
        readiness -= 20
        weaknesses.append(
            "Applicant eligibility requires verification."
        )
    elif role.role == "REJECT":
        blockers.extend(
            role.blockers or ["Opportunity rejected by applicant-role gate."]
        )

    burden = 0

    if full.cost_sharing is True or match_requirements:
        burden += 20
        weaknesses.append(
            "Match/cost-sharing increases application burden."
        )

    if len(attachments) >= 5:
        burden += 10

    if len(requirements) >= 20:
        burden += 10

    readiness = max(0, min(100, readiness))

    competitiveness = round(
        mission_fit * 0.55
        + readiness * 0.45
    )

    final_score = max(
        0,
        min(
            100,
            competitiveness - burden // 2,
        ),
    )

    if blockers:
        final_score = 0

    priority = _priority(
        final_score,
        bool(blockers),
    )

    root = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "matching"
        / str(opportunity_id)
    )
    root.mkdir(parents=True, exist_ok=True)

    output_path = root / "competitive_match.json"

    result = CompetitiveMatch(
        opportunity_id=str(opportunity_id),
        title=full.title,
        funder=full.funder,
        applicant_role=role.to_dict(),
        mission_fit_score=mission_fit,
        readiness_score=readiness,
        competitiveness_score=competitiveness,
        burden_score=burden,
        final_score=final_score,
        priority=priority,
        strengths=list(dict.fromkeys(strengths)),
        weaknesses=list(dict.fromkeys(weaknesses)),
        blockers=list(dict.fromkeys(blockers)),
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
