from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from grantbot.automation.review_router import classify_funding_type
from grantbot.writing.master_writer import write_answer


AGENT_ROLES: tuple[dict[str, str], ...] = (
    {
        "id": "funding_intelligence",
        "role": "Funding Intelligence Director",
        "responsibility": "Discover and triage mission-aligned public, private, and alternative capital.",
    },
    {
        "id": "eligibility_compliance",
        "role": "Eligibility and Compliance Director",
        "responsibility": "Identify eligibility gates, certifications, restrictions, and human-only commitments.",
    },
    {
        "id": "evidence_research",
        "role": "Evidence Research Director",
        "responsibility": "Separate source-backed facts, planning context, and unknowns and preserve provenance.",
    },
    {
        "id": "grant_strategy",
        "role": "Grant Strategy Director",
        "responsibility": "Translate evidence and requirements into a funder-specific pursuit strategy.",
    },
    {
        "id": "narrative_writer",
        "role": "Senior Persuasive Grant Writer",
        "responsibility": "Draft truthful, specific, persuasive responses using verified facts only.",
    },
    {
        "id": "quality_reviewer",
        "role": "Independent Quality Reviewer",
        "responsibility": "Reject unsupported claims, off-question writing, weak logic, and missed requirements.",
    },
    {
        "id": "human_review_router",
        "role": "Human Review Router",
        "responsibility": "Keep signatures, certifications, banking, debt, collateral, and final submission human-controlled.",
    },
)

HUMAN_ONLY_TERMS = (
    "signature",
    "certification",
    "certify",
    "attestation",
    "bank",
    "banking",
    "debt",
    "loan",
    "collateral",
    "guarantee",
    "match commitment",
    "cost share commitment",
    "submit",
    "submission",
)


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    funding_type: str
    pursuit_status: str
    stages: list[dict[str, Any]]
    verified_fact_count: int
    planning_fact_count: int
    missing_fact_count: int
    human_review_required: bool
    human_review_reasons: list[str]
    blockers: list[str]
    next_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_fact(raw: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status", raw.get("verification_state", "APPROVED"))).strip().upper()
    value = raw.get("value", raw.get("answer"))
    return {
        "key": str(raw.get("key", raw.get("fact_key", raw.get("id", "")))).strip(),
        "value": value,
        "status": status,
        "source": str(raw.get("source", "unknown")).strip(),
    }


def _fact_counts(facts: list[dict[str, Any]]) -> tuple[int, int, int]:
    verified = planning = missing = 0
    for raw in facts:
        fact = _normalize_fact(raw)
        if fact["status"] in {"VERIFIED", "APPROVED"} and fact["value"] not in (None, "", [], {}):
            verified += 1
        elif fact["status"] in {"DRAFT", "PLANNING", "PLANNING_CONTEXT", "REASONABLE_PROJECTION"} and fact["value"] not in (None, "", [], {}):
            planning += 1
        else:
            missing += 1
    return verified, planning, missing


def _human_review_reasons(opportunity: dict[str, Any], requirements: list[str]) -> list[str]:
    blob = " ".join(
        [
            str(opportunity.get("title") or ""),
            str(opportunity.get("description") or ""),
            str(opportunity.get("eligibility") or ""),
            " ".join(requirements),
        ]
    ).lower()
    reasons: list[str] = []
    for term in HUMAN_ONLY_TERMS:
        if term in blob:
            reasons.append(f"Human-controlled action or commitment detected: {term}")
    return list(dict.fromkeys(reasons))


def build_execution_plan(
    *,
    opportunity: dict[str, Any],
    facts: list[dict[str, Any]],
    requirements: list[str] | None = None,
    writing_quality: dict[str, Any] | None = None,
) -> ExecutionPlan:
    requirements = [str(item).strip() for item in (requirements or []) if str(item).strip()]
    verified, planning, missing = _fact_counts(facts)
    source_text = " ".join(
        str(opportunity.get(key) or "")
        for key in ("title", "funder", "agency", "description", "eligibility", "opportunity_type")
    )
    funding_type = classify_funding_type(source_text, opportunity)
    human_reasons = _human_review_reasons(opportunity, requirements)

    blockers: list[str] = []
    if not str(opportunity.get("source_url") or "").strip():
        blockers.append("Official source URL is missing and must be verified before pursuit.")
    if not str(opportunity.get("eligibility") or "").strip():
        blockers.append("Eligibility language is missing and must be verified from the official source.")
    if missing:
        blockers.append(f"{missing} required or unresolved fact(s) remain in the supplied fact set.")
    if writing_quality and not bool(writing_quality.get("passed")):
        blockers.append("Narrative quality gate has not passed.")

    stages: list[dict[str, Any]] = [
        {"stage": "DISCOVERY", "owner": "funding_intelligence", "status": "COMPLETE" if opportunity else "BLOCKED"},
        {"stage": "ELIGIBILITY", "owner": "eligibility_compliance", "status": "NEEDS_REVIEW" if not opportunity.get("eligibility") else "READY"},
        {"stage": "EVIDENCE", "owner": "evidence_research", "status": "READY" if verified else "NEEDS_USER"},
        {"stage": "STRATEGY", "owner": "grant_strategy", "status": "READY" if verified else "BLOCKED"},
        {"stage": "WRITING", "owner": "narrative_writer", "status": "READY" if verified else "BLOCKED"},
        {"stage": "QUALITY", "owner": "quality_reviewer", "status": "PASSED" if writing_quality and writing_quality.get("passed") else "PENDING"},
        {"stage": "HUMAN_REVIEW", "owner": "human_review_router", "status": "REQUIRED"},
    ]

    if blockers:
        pursuit_status = "NEEDS_USER" if verified else "BLOCKED"
    elif writing_quality and writing_quality.get("passed"):
        pursuit_status = "READY_FOR_HUMAN_REVIEW"
    else:
        pursuit_status = "READY_FOR_WRITING"

    next_actions: list[str] = []
    if not opportunity.get("source_url"):
        next_actions.append("Verify and save the official funder opportunity URL.")
    if not opportunity.get("eligibility"):
        next_actions.append("Extract applicant eligibility from the official opportunity source.")
    if missing:
        next_actions.append("Resolve missing factual fields without guessing or estimating them.")
    if not writing_quality:
        next_actions.append("Generate the funder-specific narrative and run the v25 quality gate.")
    elif not writing_quality.get("passed"):
        next_actions.append("Revise the narrative until the quality gate passes or route it to human review.")
    else:
        next_actions.append("Route the complete package to an authorized human for final review.")
    next_actions.append("Keep final submission, signatures, certifications, and binding financial actions human-controlled.")

    return ExecutionPlan(
        funding_type=funding_type,
        pursuit_status=pursuit_status,
        stages=stages,
        verified_fact_count=verified,
        planning_fact_count=planning,
        missing_fact_count=missing,
        human_review_required=True,
        human_review_reasons=human_reasons or ["Final application approval and submission are human-controlled."],
        blockers=blockers,
        next_actions=next_actions,
    )


def write_and_plan(
    *,
    opportunity: dict[str, Any],
    question: str,
    section: str,
    facts: list[dict[str, Any]],
    priorities: list[str] | None = None,
    requirements: list[str] | None = None,
    max_words: int | None = None,
    provider=None,
) -> dict[str, Any]:
    result = write_answer(
        question=question,
        section=section,
        facts=facts,
        grant_title=str(opportunity.get("title") or ""),
        funder=str(opportunity.get("funder") or opportunity.get("agency") or ""),
        priorities=priorities,
        requirements=requirements,
        max_words=max_words,
        provider=provider,
    )
    plan = build_execution_plan(
        opportunity=opportunity,
        facts=facts,
        requirements=requirements,
        writing_quality=result.quality,
    )
    return {
        "writer": result.to_dict(),
        "execution_plan": plan.to_dict(),
        "safe_to_submit": False,
    }
