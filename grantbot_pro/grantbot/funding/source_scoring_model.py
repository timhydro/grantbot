from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Any


MODEL_VERSION = "source-aware-v23.1"

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'-]{1,}", re.IGNORECASE)
STOPWORDS = {
    "and", "the", "for", "with", "from", "that", "this", "will", "are",
    "was", "were", "have", "has", "into", "their", "your", "our", "its",
    "program", "grant", "funding", "funds", "award", "applicant", "applicants",
    "eligible", "eligibility", "organization", "organizations", "project",
}

US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
}

ARCHETYPE_BY_KIND = {
    "GOVERNMENT": "GOVERNMENT",
    "WORKFORCE_BOARD": "GOVERNMENT",
    "CONTINUUM_OF_CARE": "GOVERNMENT",
    "COMMUNITY_REDEVELOPMENT": "GOVERNMENT",
    "COMMUNITY_FOUNDATION": "FOUNDATION",
    "FOUNDATION": "FOUNDATION",
    "FAMILY_FOUNDATION": "FOUNDATION",
    "CORPORATE": "CORPORATE",
    "SPONSOR": "CORPORATE",
    "FAITH_BASED": "FAITH",
    "CHURCH": "FAITH",
    "CDFI": "CAPITAL",
    "BANK": "CAPITAL",
    "ANGEL_NETWORK": "CAPITAL",
    "IMPACT_INVESTOR": "CAPITAL",
    "PHILANTHROPIC_INVESTOR": "CAPITAL",
}

WEIGHTS: dict[str, dict[str, float]] = {
    "GOVERNMENT": {
        "eligibility": 0.24,
        "mission_fit": 0.10,
        "program_fit": 0.10,
        "geography_fit": 0.12,
        "funding_fit": 0.07,
        "deadline_feasibility": 0.12,
        "organizational_readiness": 0.12,
        "strategic_value": 0.07,
        "relationship_fit": 0.02,
        "capital_structure_fit": 0.04,
    },
    "FOUNDATION": {
        "eligibility": 0.15,
        "mission_fit": 0.19,
        "program_fit": 0.16,
        "geography_fit": 0.12,
        "funding_fit": 0.08,
        "deadline_feasibility": 0.07,
        "organizational_readiness": 0.08,
        "strategic_value": 0.08,
        "relationship_fit": 0.05,
        "capital_structure_fit": 0.02,
    },
    "CORPORATE": {
        "eligibility": 0.13,
        "mission_fit": 0.14,
        "program_fit": 0.14,
        "geography_fit": 0.14,
        "funding_fit": 0.07,
        "deadline_feasibility": 0.07,
        "organizational_readiness": 0.08,
        "strategic_value": 0.10,
        "relationship_fit": 0.08,
        "capital_structure_fit": 0.05,
    },
    "FAITH": {
        "eligibility": 0.13,
        "mission_fit": 0.20,
        "program_fit": 0.16,
        "geography_fit": 0.07,
        "funding_fit": 0.06,
        "deadline_feasibility": 0.07,
        "organizational_readiness": 0.08,
        "strategic_value": 0.10,
        "relationship_fit": 0.08,
        "capital_structure_fit": 0.05,
    },
    "CAPITAL": {
        "eligibility": 0.18,
        "mission_fit": 0.10,
        "program_fit": 0.10,
        "geography_fit": 0.05,
        "funding_fit": 0.09,
        "deadline_feasibility": 0.05,
        "organizational_readiness": 0.10,
        "strategic_value": 0.10,
        "relationship_fit": 0.05,
        "capital_structure_fit": 0.18,
    },
    "GENERAL": {
        "eligibility": 0.20,
        "mission_fit": 0.15,
        "program_fit": 0.14,
        "geography_fit": 0.10,
        "funding_fit": 0.08,
        "deadline_feasibility": 0.09,
        "organizational_readiness": 0.09,
        "strategic_value": 0.08,
        "relationship_fit": 0.04,
        "capital_structure_fit": 0.03,
    },
}

READINESS_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "GOVERNMENT": (
        ("legal", "tax_exempt", "501c3", "501(c)(3)", "incorporation"),
        ("registration", "sam", "uei", "grants.gov"),
        ("board", "governance", "conflict_of_interest"),
        ("financial", "accounting", "budget", "audit"),
        ("program", "population", "service_area", "housing", "reentry", "workforce"),
    ),
    "FOUNDATION": (
        ("mission", "vision", "population"),
        ("program", "housing", "reentry", "workforce"),
        ("board", "leadership", "governance"),
        ("financial", "budget", "revenue", "expenses"),
        ("outcome", "evaluation", "metric"),
    ),
    "CORPORATE": (
        ("mission", "population", "community"),
        ("program", "workforce", "employment", "housing"),
        ("leadership", "board", "governance"),
        ("budget", "financial"),
        ("outcome", "metric", "impact"),
    ),
    "FAITH": (
        ("mission", "vision", "faith", "ministry"),
        ("program", "population", "housing", "reentry"),
        ("leadership", "board", "governance"),
        ("budget", "financial"),
    ),
    "CAPITAL": (
        ("legal", "entity", "incorporation", "tax_exempt"),
        ("financial", "budget", "revenue", "expenses", "cash_flow"),
        ("property", "site", "housing", "construction", "asset"),
        ("unit_cost", "unit_economics", "capital", "project_cost"),
        ("repayment", "earned_income", "social_enterprise", "sustainability"),
    ),
    "GENERAL": (
        ("mission", "vision"),
        ("program", "population"),
        ("board", "leadership"),
        ("budget", "financial"),
    ),
}

STRATEGIES: dict[str, dict[str, Any]] = {
    "GOVERNMENT": {
        "review_focus": [
            "hard eligibility and geographic restrictions",
            "mandatory registrations and certifications",
            "allowable costs, match, procurement, and reporting burden",
            "public-safety, measurable outcomes, cost effectiveness, and taxpayer value",
        ],
        "writing_emphasis": [
            "regulatory compliance",
            "quantified outcomes",
            "implementation readiness",
            "cost effectiveness",
        ],
    },
    "FOUNDATION": {
        "review_focus": [
            "mission and population alignment",
            "geographic giving footprint",
            "relationship or invitation requirements",
            "measurable community transformation and sustainability",
        ],
        "writing_emphasis": [
            "human dignity",
            "community restoration",
            "holistic support",
            "measurable impact",
        ],
    },
    "CORPORATE": {
        "review_focus": [
            "local community footprint",
            "workforce and economic-mobility alignment",
            "sponsorship, in-kind, equipment, or grant mechanism fit",
            "measurable community benefit and employee-engagement potential",
        ],
        "writing_emphasis": [
            "local visibility",
            "workforce outcomes",
            "community benefit",
            "replicable impact",
        ],
    },
    "FAITH": {
        "review_focus": [
            "mission and ministry alignment",
            "denominational or doctrinal restrictions when stated",
            "religious-use restrictions and beneficiary-access conditions",
            "community restoration and stewardship",
        ],
        "writing_emphasis": [
            "restoration",
            "dignity",
            "stewardship",
            "faith-informed service where permitted",
        ],
    },
    "CAPITAL": {
        "review_focus": [
            "legal capital structure and instrument type",
            "repayment capacity or investable-entity requirements",
            "project economics, asset/site readiness, and capital stack",
            "capital efficiency, risk controls, and measurable social return",
        ],
        "writing_emphasis": [
            "capital efficiency",
            "unit economics",
            "deployment readiness",
            "measurable social return",
        ],
    },
    "GENERAL": {
        "review_focus": [
            "eligibility",
            "mission and program fit",
            "deadline feasibility",
            "documentation and financial burden",
        ],
        "writing_emphasis": [
            "specificity",
            "evidence",
            "implementation logic",
            "measurable outcomes",
        ],
    },
}

NONPROFIT_EXCLUSION_PATTERNS = (
    re.compile(r"\bnonprofits?\s+(?:are\s+)?not\s+eligible\b", re.IGNORECASE),
    re.compile(r"\bnonprofit\s+organizations?\s+(?:are\s+)?ineligible\b", re.IGNORECASE),
    re.compile(r"\b501\s*\(c\)\s*\(3\).{0,40}\bnot\s+eligible\b", re.IGNORECASE),
    re.compile(r"\bfor[- ]profit\s+(?:entities|organizations?)\s+only\b", re.IGNORECASE),
)

NONPROFIT_POSITIVE_PATTERNS = (
    re.compile(r"\bnonprofits?\b", re.IGNORECASE),
    re.compile(r"\bnonprofit\s+organizations?\b", re.IGNORECASE),
    re.compile(r"\b501\s*\(c\)\s*\(3\)\b", re.IGNORECASE),
    re.compile(r"\bfaith[- ]based\s+organizations?\b", re.IGNORECASE),
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 2)


def _tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_RE.findall(text)
        if token.casefold() not in STOPWORDS
    }


def _lexical_fit(left: str, right: str, *, neutral: float = 45.0) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return neutral
    overlap = len(left_tokens & right_tokens)
    if overlap == 0:
        return 20.0
    denominator = max(1, min(len(left_tokens), len(right_tokens)))
    ratio = overlap / denominator
    return _clamp(25 + 75 * math.sqrt(ratio))


def archetype_for(source: dict[str, Any]) -> str:
    kind = _clean(source.get("source_kind") or source.get("source_type")).upper()
    return ARCHETYPE_BY_KIND.get(kind, "GENERAL")


def _eligibility(
    opportunity: dict[str, Any],
    source: dict[str, Any],
    organization: dict[str, Any],
) -> tuple[float, str, list[str], list[str], list[str]]:
    text = _clean(opportunity.get("eligibility"))
    blockers: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []
    if any(pattern.search(text) for pattern in NONPROFIT_EXCLUSION_PATTERNS):
        blockers.append("Opportunity text explicitly excludes nonprofit applicants.")
        return 0.0, "INELIGIBLE", blockers, warnings, reasons

    nonprofit_fit = _clean(source.get("nonprofit_fit") or "DIRECT").upper()
    requires_investable = bool(source.get("requires_investable_entity"))
    has_investable = bool(organization.get("has_investable_entity"))

    if requires_investable and not has_investable:
        blockers.append(
            "Funding source requires an investable entity, but no verified investable "
            "entity is present in the organizational fact record."
        )
        reasons.append("Capital-structure eligibility requires factual confirmation.")
        return 25.0, "NEEDS_INFORMATION", blockers, warnings, reasons

    if nonprofit_fit == "INDIRECT":
        warnings.append(
            "Source is classified as indirect nonprofit fit and requires an appropriate "
            "capital or affiliated-entity structure."
        )
        return 45.0, "CONDITIONAL", blockers, warnings, reasons
    if nonprofit_fit == "CONDITIONAL":
        warnings.append("Source is classified as conditional nonprofit fit.")
        return 65.0, "CONDITIONAL", blockers, warnings, reasons

    if text and any(pattern.search(text) for pattern in NONPROFIT_POSITIVE_PATTERNS):
        reasons.append("Opportunity text contains an affirmative nonprofit eligibility signal.")
        return 100.0, "ELIGIBLE", blockers, warnings, reasons
    if text:
        warnings.append(
            "Opportunity eligibility text was found but does not provide a decisive "
            "nonprofit eligibility signal; full source review is still required."
        )
        return 72.0, "NEEDS_INFORMATION", blockers, warnings, reasons

    warnings.append("Opportunity eligibility text is missing or incomplete.")
    return 58.0, "NEEDS_INFORMATION", blockers, warnings, reasons


def _states(text: str) -> set[str]:
    lower = text.casefold()
    return {state for state in US_STATES if state in lower}


def _geography(
    opportunity: dict[str, Any],
    source: dict[str, Any],
    organization: dict[str, Any],
) -> tuple[float, list[str], list[str], list[str]]:
    opportunity_geo = _clean(opportunity.get("geography"))
    source_geo = _clean(source.get("geography") or source.get("source_geography"))
    organization_geo = _clean(organization.get("geography_text"))
    blockers: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []

    org_states = _states(organization_geo)
    restriction_states = _states(opportunity_geo)
    if org_states and restriction_states and org_states.isdisjoint(restriction_states):
        blockers.append(
            "Opportunity has an explicit state geography that does not match the "
            "verified organizational geography."
        )
        return 0.0, blockers, warnings, reasons

    combined_restriction = f"{opportunity_geo} {source_geo}".casefold()
    if any(term in combined_restriction for term in ("united states", "nationwide", "national")):
        reasons.append("Funding geography is national or United States-wide.")
        return 95.0, blockers, warnings, reasons

    if org_states:
        source_states = _states(source_geo)
        if restriction_states & org_states or source_states & org_states:
            reasons.append("Funding geography aligns with verified organizational geography.")
            return 100.0, blockers, warnings, reasons
        if opportunity_geo:
            overlap = _lexical_fit(opportunity_geo, organization_geo, neutral=55.0)
            if overlap >= 55:
                return overlap, blockers, warnings, reasons
        warnings.append("Geographic eligibility requires finer local-area verification.")
        return 70.0, blockers, warnings, reasons

    warnings.append("Verified organizational geography was not available for comparison.")
    return 55.0, blockers, warnings, reasons


def parse_deadline(value: Any) -> date | None:
    text = _clean(value)
    if not text:
        return None
    candidates = [text, text[:10]]
    for candidate in candidates:
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    for pattern in ("%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _deadline(
    opportunity: dict[str, Any],
    *,
    as_of: date,
) -> tuple[float, int | None, list[str], list[str], list[str]]:
    raw = opportunity.get("deadline")
    parsed = parse_deadline(raw)
    blockers: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []
    if parsed is None:
        warnings.append("Opportunity deadline is missing or not parseable.")
        return 50.0, None, blockers, warnings, reasons
    days = (parsed - as_of).days
    if days < 0:
        blockers.append("Opportunity deadline has passed.")
        return 0.0, days, blockers, warnings, reasons
    if days <= 3:
        warnings.append("Deadline is within three days; execution feasibility is critical.")
        return 25.0, days, blockers, warnings, reasons
    if days <= 7:
        warnings.append("Deadline is within seven days.")
        return 45.0, days, blockers, warnings, reasons
    if days <= 14:
        return 60.0, days, blockers, warnings, reasons
    if days <= 30:
        return 78.0, days, blockers, warnings, reasons
    reasons.append("Deadline provides more than 30 days of lead time.")
    return 100.0, days, blockers, warnings, reasons


def _fact_corpus(organization: dict[str, Any]) -> str:
    return _clean(organization.get("trusted_corpus"))


def _mission_program_scores(
    opportunity: dict[str, Any],
    source: dict[str, Any],
    organization: dict[str, Any],
) -> tuple[float, float, list[str], list[str]]:
    corpus = _fact_corpus(organization)
    opportunity_text = " ".join(
        _clean(opportunity.get(key))
        for key in ("title", "description", "eligibility", "raw_text")
    )
    issue_areas = " ".join(str(item) for item in source.get("issue_areas", []) or [])
    warnings: list[str] = []
    reasons: list[str] = []
    if not corpus:
        warnings.append(
            "No verified/approved organizational fact corpus was available for mission-fit scoring."
        )
        mission = 45.0
        program = _lexical_fit(opportunity_text, issue_areas, neutral=50.0)
        return mission, program, warnings, reasons
    mission = _lexical_fit(opportunity_text, corpus, neutral=50.0)
    aligned_source_areas = _lexical_fit(issue_areas, corpus, neutral=45.0)
    opportunity_source_fit = _lexical_fit(opportunity_text, issue_areas, neutral=50.0)
    program = _clamp(aligned_source_areas * 0.45 + opportunity_source_fit * 0.55)
    if mission >= 75:
        reasons.append("Opportunity language strongly overlaps verified organizational mission/population facts.")
    if program >= 75:
        reasons.append("Opportunity and funding-source issue areas align with verified program context.")
    return mission, program, warnings, reasons


def _funding_fit(opportunity: dict[str, Any], source: dict[str, Any]) -> tuple[float, list[str]]:
    warnings: list[str] = []
    mechanisms = {str(item).upper() for item in source.get("mechanisms", []) or []}
    no_fixed_amount_expected = bool(
        mechanisms & {"SPONSORSHIP", "IN_KIND", "DONATION", "EQUIPMENT"}
    )
    floor = opportunity.get("award_floor")
    ceiling = opportunity.get("award_ceiling")
    numeric = []
    for value in (floor, ceiling):
        if isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) >= 0:
            numeric.append(float(value))
    if numeric:
        return 88.0, warnings
    if no_fixed_amount_expected:
        return 78.0, warnings
    warnings.append(
        "Funding amount was not available; GrantBot will not invent a request-size fit judgment."
    )
    return 55.0, warnings


def _readiness(archetype: str, organization: dict[str, Any]) -> tuple[float, list[str]]:
    fact_index = _clean(organization.get("fact_index")).casefold()
    groups = READINESS_GROUPS.get(archetype, READINESS_GROUPS["GENERAL"])
    if not fact_index:
        return 30.0, ["Verified/approved organizational readiness facts are sparse or unavailable."]
    satisfied = sum(
        1
        for patterns in groups
        if any(pattern.casefold() in fact_index for pattern in patterns)
    )
    score = _clamp(25 + 75 * satisfied / max(1, len(groups)))
    warnings = []
    if score < 65:
        warnings.append(
            f"Organizational fact coverage is incomplete for the {archetype.lower()} source archetype."
        )
    return score, warnings


def _capital_structure(
    archetype: str,
    source: dict[str, Any],
    organization: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
    warnings: list[str] = []
    reasons: list[str] = []
    if archetype != "CAPITAL":
        return 100.0, warnings, reasons
    requires_investable = bool(source.get("requires_investable_entity"))
    requires_legal = bool(source.get("requires_legal_review"))
    has_investable = bool(organization.get("has_investable_entity"))
    if requires_investable and not has_investable:
        warnings.append("No verified investable entity is recorded for an investable-entity source.")
        return 10.0, warnings, reasons
    score = 82.0 if has_investable else 62.0
    if requires_legal:
        score -= 10
        warnings.append("Source requires legal review of the capital structure or instrument.")
    mechanisms = {str(item).upper() for item in source.get("mechanisms", []) or []}
    if "EQUITY_INVESTMENT" in mechanisms and not has_investable:
        score = min(score, 25.0)
    if mechanisms & {"LOW_INTEREST_LOAN", "LOAN", "PROGRAM_RELATED_INVESTMENT"}:
        reasons.append("Repayment capacity and capital-stack feasibility require financial review.")
    return _clamp(score), warnings, reasons


def _relationship_fit(archetype: str, source: dict[str, Any]) -> tuple[float, list[str]]:
    access = {str(item).upper() for item in source.get("access_methods", []) or []}
    warnings: list[str] = []
    score = 55.0
    if "PARTNER_REFERRAL" in access:
        score += 12
        warnings.append("Relationship or partner-referral access may materially affect competitiveness.")
    if "MANUAL" in access:
        score += 5
    if "API" in access or "PORTAL" in access:
        score += 8
    if archetype in {"FOUNDATION", "CORPORATE", "FAITH", "CAPITAL"} and "PARTNER_REFERRAL" not in access:
        score += 5
    return _clamp(score), warnings


def _strategic_value(
    archetype: str,
    source: dict[str, Any],
    mission_fit: float,
    program_fit: float,
) -> float:
    priority = source.get("search_priority")
    try:
        source_priority = _clamp(float(priority))
    except (TypeError, ValueError):
        source_priority = 50.0
    archetype_bonus = {
        "GOVERNMENT": 5.0,
        "FOUNDATION": 4.0,
        "CORPORATE": 2.0,
        "FAITH": 3.0,
        "CAPITAL": 0.0,
        "GENERAL": 0.0,
    }.get(archetype, 0.0)
    return _clamp(
        mission_fit * 0.35
        + program_fit * 0.35
        + source_priority * 0.30
        + archetype_bonus
    )


def _burden(source: dict[str, Any], archetype: str) -> tuple[float, list[str]]:
    score = {
        "GOVERNMENT": 30.0,
        "FOUNDATION": 12.0,
        "CORPORATE": 10.0,
        "FAITH": 8.0,
        "CAPITAL": 25.0,
        "GENERAL": 15.0,
    }.get(archetype, 15.0)
    warnings: list[str] = []
    if bool(source.get("requires_legal_review")):
        score += 20
        warnings.append("Legal review is required by the source profile.")
    if bool(source.get("requires_subscription")):
        score += 12
        warnings.append("Source access requires a subscription.")
    if _clean(source.get("nonprofit_fit")).upper() == "CONDITIONAL":
        score += 15
    if bool(source.get("requires_investable_entity")):
        score += 20
    return _clamp(score), warnings


def _confidence(
    opportunity: dict[str, Any],
    source: dict[str, Any],
    organization: dict[str, Any],
) -> tuple[float, list[str]]:
    signals = {
        "source_profile": bool(source.get("source_key")),
        "source_issue_areas": bool(source.get("issue_areas")),
        "source_mechanisms": bool(source.get("mechanisms")),
        "title": bool(_clean(opportunity.get("title"))),
        "description": bool(_clean(opportunity.get("description"))),
        "eligibility": bool(_clean(opportunity.get("eligibility"))),
        "geography": bool(_clean(opportunity.get("geography")) or _clean(source.get("geography"))),
        "deadline": parse_deadline(opportunity.get("deadline")) is not None,
        "funding_amount": any(
            isinstance(opportunity.get(key), (int, float))
            for key in ("award_floor", "award_ceiling")
        ),
        "trusted_org_facts": int(organization.get("trusted_fact_count", 0) or 0) > 0,
        "verified_geography": bool(_clean(organization.get("geography_text"))),
        "readiness_fact_index": bool(_clean(organization.get("fact_index"))),
    }
    score = _clamp(100 * sum(1 for value in signals.values() if value) / len(signals))
    missing = [name for name, present in signals.items() if not present]
    return score, missing


def _priority(
    *,
    score: float,
    eligibility_state: str,
    confidence_score: float,
    hard_reject: bool,
) -> str:
    if hard_reject or eligibility_state == "INELIGIBLE":
        return "REJECT"
    if eligibility_state == "NEEDS_INFORMATION" or confidence_score < 45:
        return "NEEDS INFORMATION"
    if eligibility_state == "CONDITIONAL":
        return "REVIEW"
    if score >= 80:
        return "HIGH PRIORITY"
    if score >= 65:
        return "MEDIUM PRIORITY"
    if score >= 50:
        return "REVIEW"
    return "REJECT"


def calculate_source_aware_score(
    *,
    opportunity: dict[str, Any],
    source: dict[str, Any],
    organization: dict[str, Any],
    as_of: date,
) -> dict[str, Any]:
    archetype = archetype_for(source)
    weights = WEIGHTS[archetype]
    blockers: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []

    eligibility_score, eligibility_state, items, warn, why = _eligibility(
        opportunity, source, organization
    )
    blockers.extend(items)
    warnings.extend(warn)
    reasons.extend(why)

    geography_score, items, warn, why = _geography(
        opportunity, source, organization
    )
    blockers.extend(items)
    warnings.extend(warn)
    reasons.extend(why)

    deadline_score, days_to_deadline, items, warn, why = _deadline(
        opportunity, as_of=as_of
    )
    blockers.extend(items)
    warnings.extend(warn)
    reasons.extend(why)

    mission_fit, program_fit, warn, why = _mission_program_scores(
        opportunity, source, organization
    )
    warnings.extend(warn)
    reasons.extend(why)

    funding_fit, warn = _funding_fit(opportunity, source)
    warnings.extend(warn)

    readiness_score, warn = _readiness(archetype, organization)
    warnings.extend(warn)

    capital_structure_fit, warn, why = _capital_structure(
        archetype, source, organization
    )
    warnings.extend(warn)
    reasons.extend(why)

    relationship_fit, warn = _relationship_fit(archetype, source)
    warnings.extend(warn)

    strategic_value = _strategic_value(
        archetype, source, mission_fit, program_fit
    )
    administrative_burden, warn = _burden(source, archetype)
    warnings.extend(warn)

    components = {
        "eligibility": _clamp(eligibility_score),
        "mission_fit": _clamp(mission_fit),
        "program_fit": _clamp(program_fit),
        "geography_fit": _clamp(geography_score),
        "funding_fit": _clamp(funding_fit),
        "deadline_feasibility": _clamp(deadline_score),
        "organizational_readiness": _clamp(readiness_score),
        "strategic_value": _clamp(strategic_value),
        "relationship_fit": _clamp(relationship_fit),
        "capital_structure_fit": _clamp(capital_structure_fit),
        "administrative_burden": _clamp(administrative_burden),
    }

    weighted = sum(
        components[name] * weight for name, weight in weights.items()
    )
    burden_penalty = administrative_burden * 0.10
    score = _clamp(weighted - burden_penalty)

    hard_reject = any(
        phrase in blocker.casefold()
        for blocker in blockers
        for phrase in (
            "explicitly excludes",
            "deadline has passed",
            "does not match the verified organizational geography",
        )
    )
    confidence_score, missing_signals = _confidence(
        opportunity, source, organization
    )
    priority = _priority(
        score=score,
        eligibility_state=eligibility_state,
        confidence_score=confidence_score,
        hard_reject=hard_reject,
    )

    warnings = list(dict.fromkeys(item for item in warnings if item))
    blockers = list(dict.fromkeys(item for item in blockers if item))
    reasons = list(dict.fromkeys(item for item in reasons if item))

    strategy = dict(STRATEGIES[archetype])
    strategy.update(
        {
            "archetype": archetype,
            "source_key": source.get("source_key"),
            "source_kind": source.get("source_kind"),
            "jurisdiction": source.get("jurisdiction_level") or source.get("jurisdiction"),
            "mechanisms": list(source.get("mechanisms", []) or []),
            "requires_legal_review": bool(source.get("requires_legal_review")),
            "requires_subscription": bool(source.get("requires_subscription")),
            "requires_investable_entity": bool(source.get("requires_investable_entity")),
        }
    )

    output = {
        "model_version": MODEL_VERSION,
        "as_of": as_of.isoformat(),
        "archetype": archetype,
        "overall_score": score,
        "priority": priority,
        "eligibility_state": eligibility_state,
        "confidence_score": confidence_score,
        "days_to_deadline": days_to_deadline,
        "components": components,
        "weights": dict(weights),
        "burden_penalty": round(burden_penalty, 2),
        "blockers": blockers,
        "warnings": warnings,
        "reasons": reasons,
        "missing_confidence_signals": missing_signals,
        "source_strategy": strategy,
        "methodology_note": (
            "Deterministic source-aware strategic scoring. The score is not an award "
            "probability, actuarial loss probability, or prediction of funder behavior. "
            "Hard eligibility failures override thematic fit."
        ),
    }
    material = {
        "opportunity": opportunity,
        "source": source,
        "organization_fingerprint": organization.get("fingerprint"),
        "as_of": as_of.isoformat(),
        "model_version": MODEL_VERSION,
    }
    output["input_sha256"] = hashlib.sha256(
        json.dumps(material, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return output
