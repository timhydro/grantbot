from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from grantbot.knowledge.canonical import current_facts, set_fact
from grantbot.knowledge.question_bank import QUESTIONS


TRUST_RANK = {"MISSING": 0, "UNVERIFIED": 1, "APPROVED": 2, "VERIFIED": 3}

# These keys intentionally match the current question bank. Planning context does
# not satisfy a critical item; only APPROVED/VERIFIED facts do.
CRITICAL_WEIGHTS = {
    "legal_name": 100,
    "ein": 100,
    "tax_exempt_status": 100,
    "annual_budget": 95,
    "sam": 95,
    "uei": 95,
    "grants_gov": 95,
    "financial_controls": 90,
    "financial_statements": 90,
    "current_people_served": 90,
    "annual_people_served": 90,
    "eligibility_requirements": 88,
    "program_names": 85,
    "program_model": 85,
    "revenue_sources": 85,
    "board_members": 82,
    "property_status": 80,
    "matching_funds": 80,
    "employer_partners": 78,
}

QUESTION_ALIASES: dict[str, tuple[str, ...]] = {
    "sam": ("sam", "sam_registration"),
    "grants_gov": ("grants_gov", "grants_gov_registration"),
    "length_of_stay": ("length_of_stay", "resident_length_of_stay"),
    "property_status": ("property_status", "property_ownership_status"),
    "case_management": ("case_management", "case_management_model"),
    "mentorship": ("mentorship", "mentorship_structure"),
    "life_skills": ("life_skills", "life_skills_curriculum"),
    "conflict_policy": ("conflict_policy", "conflict_of_interest_policy"),
}

CONSEQUENTIAL_KEYS = {
    "ein",
    "tax_exempt_status",
    "uei",
    "annual_budget",
    "program_budget",
    "cash_on_hand",
    "matching_funds",
    "financial_controls",
    "financial_statements",
    "audit",
    "construction_cost",
    "property_status",
    "starting_wages",
    "employer_partners",
    "current_people_served",
    "annual_people_served",
    "state_vendor",
    "county_vendor",
    "city_vendor",
    "amount_sought",
    "structure",
    "return",
    "repayment",
}


def _row(
    category: str,
    key: str,
    value: Any,
    *,
    state: str = "APPROVED",
    fact_type: str = "USER_PROVIDED_FACT",
    source: str = "Founder-approved Broken Growth profile",
    source_type: str = "founder_directive",
    confidence: float = 1.0,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "category": category,
        "fact_key": key,
        "value": value,
        "fact_type": fact_type,
        "verification_state": state,
        "source": source,
        "source_type": source_type,
        "confidence": confidence,
        "notes": notes,
    }


KNOWN_PROFILE: tuple[dict[str, Any], ...] = (
    _row("organization", "organization_name", "BrokenGrowthMinistries"),
    _row(
        "organization",
        "organization_type",
        "Florida nonprofit corporation",
        state="VERIFIED",
        fact_type="VERIFIED_FACT",
        source="Florida Sunbiz organizational record",
        source_type="official_registry",
    ),
    _row(
        "legal",
        "legal_name",
        "BROKENGROWTHMINISTRIES, INC.",
        state="VERIFIED",
        fact_type="VERIFIED_FACT",
        source="Florida Sunbiz organizational record",
        source_type="official_registry",
    ),
    _row(
        "legal",
        "state_registration_number",
        "N26000002310",
        state="VERIFIED",
        fact_type="VERIFIED_FACT",
        source="Florida Sunbiz organizational record",
        source_type="official_registry",
    ),
    _row(
        "legal",
        "date_incorporated",
        "2026-02-23",
        state="VERIFIED",
        fact_type="VERIFIED_FACT",
        source="Florida Sunbiz organizational record",
        source_type="official_registry",
    ),
    _row(
        "legal",
        "state_entity_status",
        "Active",
        state="VERIFIED",
        fact_type="VERIFIED_FACT",
        source="Florida Sunbiz organizational record",
        source_type="official_registry",
    ),
    _row(
        "legal",
        "ein_issued_status",
        "The IRS has issued the organization an EIN; the exact EIN remains a human-required application field.",
        source="Founder tax-status confirmation",
        source_type="founder_confirmation",
        notes="Do not infer or expose the EIN from this status fact.",
    ),
    _row(
        "legal",
        "tax_exempt_status",
        "IRS 501(c)(3) determination pending; no determination letter has been received.",
        source="Founder tax-status confirmation",
        source_type="founder_confirmation",
    ),
    _row("leadership", "founder_name", "Timothy Oates"),
    _row("leadership", "executive_director", "Timothy Oates"),
    _row("leadership", "board_size", 3),
    _row(
        "leadership",
        "board_members",
        ["Timothy Oates", "Gary Tompkins", "Tracy (first name provided)"],
        notes="Secretary surname has not been supplied.",
    ),
    _row("geography", "primary_geographic_focus", "Pensacola and Escambia County, Florida"),
    _row(
        "organization",
        "mission_statement",
        "BrokenGrowthMinistries provides faith-centered restoration and second chances by helping people returning from incarceration and people experiencing homelessness move toward safe housing, stability, meaningful work, supportive community, independence, and personal growth.",
    ),
    _row("organization", "faith_identity", "Christian faith-based ministry"),
    _row(
        "organization",
        "current_service_status",
        "Early community services have begun on a small scale, including food and clothing assistance and occasional paid work opportunities.",
        source="Founder current-service report",
        source_type="founder_confirmation",
        notes="This is activity context, not a quantified outcome claim.",
    ),
    _row(
        "population",
        "primary_populations",
        ["people returning from jail or prison", "people experiencing homelessness"],
    ),
    _row("population", "age_range", "Adults age 18 and older"),
    _row(
        "population",
        "eligibility_requirements",
        "For the first residential facility, adult men age 18+ may apply. Applicants are considered individually; sex-offense convictions are excluded. Applicants must have at least 30 days of sobriety before admission.",
        source_type="program_policy",
    ),
    _row(
        "program",
        "sobriety_requirement",
        "Minimum 30 days of sobriety before admission",
        source_type="program_policy",
        notes="This supersedes the earlier six-month sobriety concept.",
    ),
    _row(
        "program",
        "stabilization_period",
        "30 days after move-in before work, training, or active job-search requirements begin",
        source_type="program_policy",
    ),
    _row(
        "program",
        "program_model",
        "Integrated transitional housing, workforce development, employment support, life skills, mentorship, resource navigation, reentry support, supportive community, transportation assistance where feasible, and faith/values support.",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Founder program plan",
        source_type="program_planning",
        confidence=0.9,
    ),
    _row(
        "housing",
        "planned_tiny_homes",
        "Current base planning target of 12 Pallet-style modular sleeping shelters; final unit count requires County and engineering approval.",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Broken Growth Pallet Village planning record dated 2026-08-19",
        source_type="program_planning",
        confidence=0.85,
    ),
    _row(
        "housing",
        "project_name",
        "Broken Growth Ministries Reentry and Transitional Housing Pallet Village",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Broken Growth Pallet Village planning record dated 2026-08-19",
        source_type="program_planning",
        confidence=0.95,
    ),
    _row(
        "housing",
        "project_site_address",
        "Proposed project site: 301 Cain Ave, Pensacola, Florida 32514",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Broken Growth Pallet Village planning record dated 2026-08-19",
        source_type="program_planning",
        confidence=0.9,
        notes="Project site only; do not substitute for the organization's physical or mailing address.",
    ),
    _row(
        "housing",
        "property_status",
        "A proposed Pensacola site is in predevelopment planning. Site control, zoning, use classification, utilities, buildable capacity, and development approvals require human and agency verification.",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Broken Growth zoning pre-application planning record dated 2026-08-19",
        source_type="program_planning",
        confidence=0.8,
    ),
    _row(
        "housing",
        "pallet_shelter_model",
        "A planned 12-shelter base concept using climate-controlled modular sleeping shelters, shared private hygiene and laundry facilities, accessible circulation, safety infrastructure, and program space; final unit count and design require County and engineering approval.",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Broken Growth Pallet Village planning record dated 2026-08-19",
        source_type="program_planning",
        confidence=0.85,
    ),
    _row(
        "housing",
        "housing_capacity",
        "A 12-person base planning scenario, with any higher unit count subject to written zoning and engineered site confirmation.",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Broken Growth Pallet Village planning record dated 2026-08-19",
        source_type="program_planning",
        confidence=0.8,
    ),
    _row(
        "housing",
        "resident_length_of_stay",
        "Approximately six months to one year",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Founder residential plan",
        source_type="program_planning",
        confidence=0.8,
    ),
    _row(
        "housing",
        "resident_contribution_model",
        "A prospective, income-sensitive resident contribution of approximately 20% to 30% of earned pay, subject to affordability safeguards, legal review, and final program policy.",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Founder residential sustainability plan",
        source_type="program_planning",
        confidence=0.75,
    ),
    _row(
        "finance",
        "capital_planning_budget",
        "The current 12-shelter capital planning estimate is approximately $1,144,250 including a 15% contingency; it is not a board-approved request budget, vendor quote, or contractor bid.",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Broken Growth Pallet Village planning budget dated 2026-08-19",
        source_type="planning_estimate",
        confidence=0.75,
    ),
    _row(
        "employment",
        "training_program",
        ["construction", "landscaping", "carpentry", "plumbing", "welding", "food service", "maintenance", "computer skills"],
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Founder workforce plan",
        source_type="program_planning",
        confidence=0.85,
    ),
    _row(
        "population",
        "projected_people_served",
        "First-year planning target of 30 to 50 participants",
        state="UNVERIFIED",
        fact_type="REASONABLE_PROJECTION",
        source="Founder first-year plan",
        source_type="program_planning",
        confidence=0.8,
    ),
    _row(
        "grant_readiness",
        "sam_registration",
        "Registered on SAM.gov; treat registration as completed/active unless the founder updates the status.",
        source="Founder registration confirmation",
        source_type="founder_confirmation",
    ),
    _row(
        "grant_readiness",
        "grants_gov_registration",
        "Registered on Grants.gov; treat registration as completed/active unless the founder updates the status.",
        source="Founder registration confirmation",
        source_type="founder_confirmation",
    ),
    _row(
        "funding",
        "funding_source_scope",
        ["city", "county", "state", "federal", "foundation", "corporate", "faith-based", "community development", "housing", "reentry", "workforce", "homelessness", "economic development", "capital/construction", "equipment", "operating", "program", "matching", "in-kind", "angel investors", "impact investment"],
    ),
)


@dataclass(frozen=True, slots=True)
class QuestionStatus:
    category: str
    fact_key: str
    question: str
    priority: int
    state: str
    matched_fact_key: str | None
    verification_state: str | None
    value: Any
    requires_confirmation: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "fact_key": self.fact_key,
            "question": self.question,
            "priority": self.priority,
            "state": self.state,
            "matched_fact_key": self.matched_fact_key,
            "verification_state": self.verification_state,
            "value": self.value,
            "requires_confirmation": self.requires_confirmation,
        }


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _index() -> dict[str, dict[str, Any]]:
    return {str(item["fact_key"]): item for item in current_facts()}


def seed_known_profile(*, actor: str = "knowledge-v23-seed") -> dict[str, Any]:
    existing = _index()
    created = 0
    upgraded = 0
    skipped = 0
    conflicts: list[dict[str, Any]] = []

    for candidate in KNOWN_PROFILE:
        key = str(candidate["fact_key"])
        current = existing.get(key)
        if current is not None:
            old_state = str(current.get("verification_state", "MISSING")).upper()
            new_state = str(candidate["verification_state"]).upper()
            old_value = current.get("value")
            new_value = candidate["value"]
            old_rank = TRUST_RANK.get(old_state, 0)
            new_rank = TRUST_RANK.get(new_state, 0)
            same_value = _stable(old_value) == _stable(new_value)

            if same_value and old_rank >= new_rank:
                skipped += 1
                continue
            if not same_value and old_rank >= new_rank and _has_value(old_value):
                conflicts.append({
                    "fact_key": key,
                    "existing_value": old_value,
                    "existing_state": old_state,
                    "candidate_value": new_value,
                    "candidate_state": new_state,
                    "action": "PRESERVED_EXISTING",
                })
                skipped += 1
                continue
            upgraded += 1
        else:
            created += 1

        saved = set_fact(
            category=str(candidate["category"]),
            fact_key=key,
            value=candidate["value"],
            fact_type=str(candidate["fact_type"]),
            verification_state=str(candidate["verification_state"]),
            source=str(candidate["source"]),
            source_type=str(candidate["source_type"]),
            confidence=float(candidate["confidence"]),
            notes=str(candidate.get("notes", "")),
            actor=actor,
        )
        existing[key] = saved

    return {
        "created": created,
        "upgraded": upgraded,
        "skipped": skipped,
        "conflicts": conflicts,
        "profile_fact_count": len(KNOWN_PROFILE),
    }


def question_statuses() -> list[QuestionStatus]:
    facts = _index()
    output: list[QuestionStatus] = []
    for question in QUESTIONS:
        matched_key: str | None = None
        matched: dict[str, Any] | None = None
        for key in QUESTION_ALIASES.get(question.key, (question.key,)):
            candidate = facts.get(key)
            if candidate is not None and _has_value(candidate.get("value")):
                matched_key = key
                matched = candidate
                break

        if matched is None:
            state = "MISSING"
            verification = None
            value = None
        else:
            verification = str(matched.get("verification_state", "UNVERIFIED")).upper()
            value = matched.get("value")
            state = "ANSWERED" if verification in {"APPROVED", "VERIFIED"} else "PLANNING_CONTEXT"

        output.append(QuestionStatus(
            category=question.category,
            fact_key=question.key,
            question=question.question,
            priority=question.priority,
            state=state,
            matched_fact_key=matched_key,
            verification_state=verification,
            value=value,
            requires_confirmation=(question.key in CONSEQUENTIAL_KEYS and state != "ANSWERED"),
        ))
    return output


def next_questions(limit: int = 20) -> list[dict[str, Any]]:
    if not 1 <= int(limit) <= 200:
        raise ValueError("limit must be between 1 and 200")
    pending = [item for item in question_statuses() if item.state != "ANSWERED"]
    pending.sort(key=lambda item: (
        0 if item.requires_confirmation else 1,
        item.priority,
        -CRITICAL_WEIGHTS.get(item.fact_key, 0),
        item.category,
        item.fact_key,
    ))
    return [item.to_dict() for item in pending[: int(limit)]]


def readiness_summary() -> dict[str, Any]:
    statuses = question_statuses()
    answered = sum(item.state == "ANSWERED" for item in statuses)
    planning = sum(item.state == "PLANNING_CONTEXT" for item in statuses)
    missing = sum(item.state == "MISSING" for item in statuses)

    weighted_total = sum(CRITICAL_WEIGHTS.values())
    pending_keys = {item.fact_key for item in statuses if item.state != "ANSWERED"}
    weighted_pending = sum(
        weight for key, weight in CRITICAL_WEIGHTS.items() if key in pending_keys
    )
    score = 0.0 if weighted_total == 0 else round(
        100 * (1 - weighted_pending / weighted_total), 1
    )

    return {
        "version": "23.0",
        "question_bank_size": len(statuses),
        "answered": answered,
        "planning_context": planning,
        "missing": missing,
        "readiness_score": max(0.0, min(100.0, score)),
        "critical_missing": [
            item.to_dict()
            for item in statuses
            if item.fact_key in CRITICAL_WEIGHTS and item.state != "ANSWERED"
        ],
        "next_questions": next_questions(limit=20),
    }


def grant_safe_profile() -> dict[str, Any]:
    output: dict[str, Any] = {}
    for fact in current_facts(verification_states=["APPROVED", "VERIFIED"]):
        if not _has_value(fact.get("value")):
            continue
        output[str(fact["fact_key"])] = {
            "value": fact.get("value"),
            "verification_state": fact.get("verification_state"),
            "source": fact.get("source"),
            "confidence": fact.get("confidence"),
            "category": fact.get("category"),
        }
    return output
