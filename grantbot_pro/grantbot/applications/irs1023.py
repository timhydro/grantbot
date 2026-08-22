from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from grantbot.agents.crewai_multimodel import (
    extract_final_answer,
    kickoff_multimodel_grant_crew,
    role_plan_status,
)
from grantbot.applications.review_workspace import (
    ReviewField,
    ReviewPacket,
    ReviewStatus,
    save_review_packet,
)
from grantbot.knowledge.canonical import current_facts

IRS_FORM_1023_SOURCE = "https://www.irs.gov/instructions/i1023"
IRS_FORM_1023_REVISION = "12/2024 continuous-use"
IRS_FORM_1023_PAYGOV = "https://www.pay.gov/public/form/start/704509645"
PACKAGE_ID = "irs-form-1023-broken-growth"

TRUSTED_STATES = {"VERIFIED", "APPROVED"}
USABLE_STATES = {"VERIFIED", "APPROVED", "UNVERIFIED", "MISSING"}

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "legal_name": ("legal_name", "organization_name", "name"),
    "mailing_address": ("mailing_address", "organization_address", "address"),
    "ein": ("ein", "employer_identification_number"),
    "tax_year_end": ("tax_year_end", "fiscal_year_end"),
    "contact_name": ("contact_name", "person_to_contact", "executive_director", "founder_name"),
    "contact_phone": ("contact_phone", "phone", "telephone"),
    "fax": ("fax", "fax_number"),
    "website": ("website", "website_url"),
    "officers_directors": ("officers_directors", "board_members", "leadership"),
    "entity_type": ("entity_type", "organization_type", "legal_structure"),
    "formation_date": ("formation_date", "date_formed", "incorporation_date"),
    "state_of_formation": ("state_of_formation", "formation_state", "incorporation_state"),
    "bylaws_adopted": ("bylaws_adopted", "has_bylaws"),
    "successor_organization": ("successor_organization", "is_successor"),
    "purpose_clause_location": ("purpose_clause_location", "purpose_clause_reference"),
    "dissolution_clause_location": ("dissolution_clause_location", "dissolution_clause_reference"),
    "ntee_code": ("ntee_code",),
    "authorized_signer": ("authorized_signer", "signer", "executive_director"),
}

STATIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("Legal name", "legal_name"),
    ("Mailing address", "mailing_address"),
    ("Employer Identification Number (EIN)", "ein"),
    ("Tax year end", "tax_year_end"),
    ("Person to contact", "contact_name"),
    ("Contact telephone", "contact_phone"),
    ("Fax", "fax"),
    ("Website", "website"),
    ("Officers / directors / trustees", "officers_directors"),
    ("Entity type", "entity_type"),
    ("Formation date", "formation_date"),
    ("State of formation", "state_of_formation"),
    ("Bylaws adopted", "bylaws_adopted"),
    ("Successor organization", "successor_organization"),
    ("Purpose clause location", "purpose_clause_location"),
    ("Dissolution clause location", "dissolution_clause_location"),
    ("NTEE code", "ntee_code"),
    ("Authorized signer", "authorized_signer"),
)


@dataclass(frozen=True, slots=True)
class IRSQuestion:
    question_id: str
    part: str
    label: str
    prompt: str
    section: str = "general"
    max_words: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CORE_QUESTIONS: tuple[IRSQuestion, ...] = (
    IRSQuestion(
        "IV-1",
        "Part IV",
        "Detailed description of past, present, and planned activities",
        (
            "Describe completely and in detail the organization's past, present, and planned activities. "
            "For each activity explain what it is, who conducts it, where it occurs, the percentage of total "
            "organizational time devoted to it, how it is funded and the share of expenses allocated to it, "
            "and how it furthers the organization's section 501(c)(3) exempt purposes."
        ),
        "program_design",
        1600,
    ),
    IRSQuestion(
        "IV-3",
        "Part IV",
        "Selection of individuals receiving program benefits",
        (
            "If programs are limited to specific individuals, explain how the organization selects or identifies "
            "the people who receive services, assistance, housing, employment support, or other program benefits."
        ),
        "program_design",
        700,
    ),
    IRSQuestion(
        "IV-4",
        "Part IV",
        "Relationships with beneficiaries",
        (
            "Describe any business or family relationship between people receiving goods, services, or funds "
            "through the organization's programs and any officer, director, trustee, or highly compensated person."
        ),
        "organizational_capacity",
        500,
    ),
    IRSQuestion(
        "IV-POLITICAL",
        "Part IV",
        "Political campaign and lobbying activities",
        (
            "Describe whether the organization participates or plans to participate in political campaign "
            "intervention, lobbying, nonpartisan voter education, voter registration, or other legislative activity. "
            "Distinguish prohibited campaign intervention from any permitted nonpartisan or insubstantial activity."
        ),
        "organizational_capacity",
        700,
    ),
    IRSQuestion(
        "V-COMP",
        "Part V",
        "Compensation and financial arrangements",
        (
            "Describe compensation arrangements for officers, directors, trustees, employees, independent "
            "contractors, and related parties, including how compensation is approved and how conflicts of interest "
            "and fair-market-value safeguards are handled."
        ),
        "organizational_capacity",
        900,
    ),
    IRSQuestion(
        "V-CONFLICTS",
        "Part V",
        "Conflict-of-interest safeguards",
        (
            "Describe the organization's conflict-of-interest safeguards and how transactions involving insiders, "
            "related parties, leases, loans, management services, joint ventures, or other financial arrangements "
            "are reviewed and approved."
        ),
        "organizational_capacity",
        800,
    ),
    IRSQuestion(
        "VI-FINANCIAL",
        "Part VI",
        "Financial data and projections",
        (
            "Explain the basis for the organization's financial data and projections, including revenue sources, "
            "program expenses, administrative expenses, fundraising expenses, assets, liabilities, and any material "
            "assumptions. Do not invent amounts that are not present in the source record."
        ),
        "budget_narrative",
        1000,
    ),
    IRSQuestion(
        "VII-CLASS",
        "Part VII",
        "Foundation classification",
        (
            "Explain the organization's requested public-charity or private-foundation classification and the factual "
            "basis for the classification, including expected sources of public support or program-service revenue."
        ),
        "organizational_capacity",
        800,
    ),
    IRSQuestion(
        "VIII-EFFECTIVE",
        "Part VIII",
        "Effective date and filing timing",
        (
            "Explain the organization's formation date, intended effective date of exemption, filing timing, and any "
            "facts relevant to the 27-month filing rule or Schedule E. Do not infer dates that are not verified."
        ),
        "general",
        600,
    ),
    IRSQuestion(
        "IX-990",
        "Part IX",
        "Annual filing requirements",
        (
            "State whether the organization expects to claim an exception from Form 990-series annual filing "
            "requirements and explain the factual basis. If no verified exception is established, say that the "
            "organization should not claim one without human review."
        ),
        "organizational_capacity",
        500,
    ),
    IRSQuestion(
        "SCHEDULE-F",
        "Schedule F",
        "Low-income housing supplemental narrative",
        (
            "If Schedule F applies, describe the organization's housing program, target residents, affordability "
            "approach, facilities, admission process, public availability, resident agreements, any joint ventures, "
            "and how the housing program furthers charitable purposes. Clearly identify any facts still missing."
        ),
        "program_design",
        1400,
    ),
)


def _normalize_fact(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact_key": str(raw.get("fact_key", raw.get("key", ""))).strip().lower(),
        "category": str(raw.get("category", "general")).strip().lower(),
        "value": raw.get("value", raw.get("answer")),
        "verification_state": str(raw.get("verification_state", raw.get("status", ""))).strip().upper(),
        "source": str(raw.get("source", "")).strip(),
        "notes": str(raw.get("notes", "")).strip(),
    }


def _facts() -> list[dict[str, Any]]:
    return [
        _normalize_fact(item)
        for item in current_facts(verification_states=list(USABLE_STATES))
    ]


def _index(facts: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for fact in facts:
        key = str(fact.get("fact_key", "")).strip().lower()
        if key:
            result[key] = fact
    return result


def _field_value(
    key: str,
    fact_index: dict[str, dict[str, Any]],
) -> ReviewField:
    aliases = FIELD_ALIASES[key]
    for alias in aliases:
        fact = fact_index.get(alias)
        if fact is None:
            continue
        state = str(fact.get("verification_state", "")).upper()
        value = fact.get("value")
        if value in (None, "", [], {}):
            continue
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        return ReviewField(
            label=key,
            value=rendered,
            source=str(fact.get("source") or f"canonical:{alias}"),
            requires_user_confirmation=state not in TRUSTED_STATES,
        )
    return ReviewField(
        label=key,
        value=None,
        source="canonical knowledge: missing",
        requires_user_confirmation=True,
    )


def _dossier(facts: list[dict[str, Any]]) -> str:
    lines = [
        "FORM: IRS Form 1023, Application for Recognition of Exemption Under Section 501(c)(3)",
        f"OFFICIAL INSTRUCTIONS: {IRS_FORM_1023_SOURCE}",
        f"REVISION: {IRS_FORM_1023_REVISION}",
        "",
        "CANONICAL ORGANIZATION FACTS:",
    ]
    for fact in facts:
        value = fact.get("value")
        lines.append(
            f"- [{fact.get('verification_state')}] "
            f"{fact.get('category')}.{fact.get('fact_key')}: "
            f"{json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)} "
            f"(source: {fact.get('source') or 'unspecified'})"
        )
    lines.extend(
        [
            "",
            "RULES:",
            "- VERIFIED and APPROVED facts may be stated as facts.",
            "- UNVERIFIED facts require human confirmation and may not be converted into certainty.",
            "- MISSING facts may not be guessed.",
            "- This workflow prepares and reviews Form 1023; it never signs or submits to Pay.gov.",
        ]
    )
    return "\n".join(lines)


def detect_schedule_flags(facts: list[dict[str, Any]]) -> dict[str, str]:
    searchable = " ".join(
        f"{fact.get('fact_key', '')} {fact.get('category', '')} {fact.get('value', '')}"
        for fact in facts
    ).lower()
    flags = {
        "A": "NOT_INDICATED",
        "B": "NOT_INDICATED",
        "C": "NOT_INDICATED",
        "D": "NOT_INDICATED",
        "E": "REQUIRES_DATE_REVIEW",
        "F": "NOT_INDICATED",
        "G": "REQUIRES_SUCCESSOR_REVIEW",
        "H": "NOT_INDICATED",
    }
    housing_terms = (
        "low-income housing",
        "affordable housing",
        "tiny home",
        "tiny-home",
        "transitional housing",
        "supportive housing",
    )
    if any(term in searchable for term in housing_terms):
        flags["F"] = "POTENTIALLY_REQUIRED"
    scholarship_terms = ("scholarship", "fellowship", "educational loan", "grant to individual")
    if any(term in searchable for term in scholarship_terms):
        flags["H"] = "POTENTIALLY_REQUIRED"
    return flags


def irs1023_status() -> dict[str, Any]:
    facts = _facts()
    return {
        "form": "IRS Form 1023",
        "revision": IRS_FORM_1023_REVISION,
        "official_instructions": IRS_FORM_1023_SOURCE,
        "paygov": IRS_FORM_1023_PAYGOV,
        "required_parts": [f"Part {roman}" for roman in ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")],
        "schedule_flags": detect_schedule_flags(facts),
        "canonical_fact_count": len(facts),
        "multi_model": role_plan_status(),
        "human_review_required": True,
        "submission_performed": False,
        "safe_to_submit": False,
    }


def answer_question(
    question: IRSQuestion,
    *,
    facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_facts = facts if facts is not None else _facts()
    run = kickoff_multimodel_grant_crew(
        dossier=_dossier(source_facts),
        question=f"{question.part} — {question.label}\n\n{question.prompt}",
        max_words=question.max_words,
    )
    final_answer = extract_final_answer(run.output)
    return {
        "question": question.to_dict(),
        "status": run.status,
        "answer": final_answer,
        "review_output": run.output,
        "role_models": run.role_models,
        "artifact_path": run.artifact_path,
        "artifact_sha256": run.artifact_sha256,
        "human_review_required": True,
        "submission_performed": False,
        "safe_to_submit": False,
    }


def build_irs1023_review_packet(
    *,
    generate_ai: bool = True,
    question_ids: list[str] | None = None,
) -> tuple[ReviewPacket, str, list[dict[str, Any]]]:
    facts = _facts()
    fact_index = _index(facts)
    fields: list[ReviewField] = []
    missing: list[str] = []

    for label, key in STATIC_FIELDS:
        field = _field_value(key, fact_index)
        fields.append(
            ReviewField(
                label=label,
                value=field.value,
                source=field.source,
                requires_user_confirmation=field.requires_user_confirmation,
            )
        )
        if field.value in (None, ""):
            missing.append(label)
        elif field.requires_user_confirmation:
            missing.append(f"Confirm {label}")

    selected_ids = set(question_ids) if question_ids is not None else None
    selected = [
        question
        for question in CORE_QUESTIONS
        if selected_ids is None or question.question_id in selected_ids
    ]

    schedule_flags = detect_schedule_flags(facts)
    if schedule_flags["F"] != "POTENTIALLY_REQUIRED":
        selected = [question for question in selected if question.question_id != "SCHEDULE-F"]

    ai_results: list[dict[str, Any]] = []
    if generate_ai:
        for question in selected:
            result = answer_question(question, facts=facts)
            ai_results.append(result)
            fields.append(
                ReviewField(
                    label=f"{question.part} — {question.label}",
                    value=result.get("answer"),
                    source=f"multi-model CrewAI staged artifact {result['artifact_sha256']}",
                    requires_user_confirmation=True,
                )
            )
            if not result.get("answer"):
                missing.append(f"AI answer requires remediation: {question.question_id}")
            else:
                missing.append(f"Review and approve {question.question_id}")

    schedule_notes = [
        f"Schedule {letter}: {state}"
        for letter, state in schedule_flags.items()
    ]
    packet = ReviewPacket(
        opportunity_id=PACKAGE_ID,
        opportunity_name="Broken Growth Ministries — IRS Form 1023",
        funding_type="IRS 501(c)(3) recognition application",
        status=ReviewStatus.NEEDS_USER,
        source_url=IRS_FORM_1023_SOURCE,
        deadline=None,
        requested_amount=None,
        fields=fields,
        missing_items=list(dict.fromkeys(missing)),
        submission_steps=[
            "Resolve every missing or confirmation-required field.",
            "Review all AI-generated narratives against canonical facts and source documents.",
            "Confirm which Form 1023 schedules A-H apply.",
            "Assemble organizing document, amendments, bylaws, and required supplemental responses into one PDF.",
            "Verify the attachment PDF meets the current Pay.gov size and formatting requirements.",
            "Have an authorized officer listed in Part I review the complete application.",
            "Enter the human-approved answers in Pay.gov.",
            "Authorized human signer certifies and submits the application and user fee.",
            "Store the Pay.gov/IRS submission receipt in GrantBot after filing.",
        ],
        notes=[
            f"Official IRS instructions: {IRS_FORM_1023_SOURCE}",
            f"Form instructions revision: {IRS_FORM_1023_REVISION}",
            "All applicants generally complete Parts I-X plus applicable schedules and attachments.",
            "GrantBot does not sign, certify, pay, or submit the IRS application.",
            *schedule_notes,
        ],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    folder = save_review_packet(packet)
    return packet, str(folder), ai_results
