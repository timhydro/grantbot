from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from grantbot import __app_name__, __organization__, __version__
from grantbot.agents.crewai_single_voice import run_single_voice_pipeline, single_voice_status
from grantbot.applications.irs1023 import (
    CORE_QUESTIONS,
    FIELD_ALIASES,
    IRS_FORM_1023_PAYGOV,
    IRS_FORM_1023_REVISION,
    IRS_FORM_1023_SOURCE,
    PACKAGE_ID,
    STATIC_FIELDS,
    detect_schedule_flags,
)
from grantbot.applications.review_workspace import ReviewField, ReviewPacket, ReviewStatus, save_review_packet
from grantbot.knowledge.canonical import current_facts


TRUSTED_STATES = {"VERIFIED", "APPROVED"}
ACTIVE_STATES = ["VERIFIED", "APPROVED", "UNVERIFIED", "MISSING"]


def _facts() -> list[dict[str, Any]]:
    return current_facts(verification_states=ACTIVE_STATES)


def _fact_index(facts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in facts:
        key = str(item.get("fact_key", "")).strip().lower()
        if key:
            result[key] = item
    return result


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _static_field(key: str, index: dict[str, dict[str, Any]]) -> ReviewField:
    for alias in FIELD_ALIASES[key]:
        fact = index.get(alias)
        if not fact:
            continue
        value = fact.get("value")
        if value in (None, "", [], {}):
            continue
        state = str(fact.get("verification_state", "")).upper()
        return ReviewField(
            label=key,
            value=_render_value(value),
            source=str(fact.get("source") or f"canonical:{alias}"),
            requires_user_confirmation=state not in TRUSTED_STATES,
        )
    return ReviewField(
        label=key,
        value=None,
        source="canonical knowledge: missing",
        requires_user_confirmation=True,
    )


def production_status() -> dict[str, Any]:
    facts = _facts()
    return {
        "name": __app_name__,
        "organization": __organization__,
        "version": __version__,
        "production_pipeline": single_voice_status(),
        "canonical_fact_count": len(facts),
        "irs1023": {
            "revision": IRS_FORM_1023_REVISION,
            "official_instructions": IRS_FORM_1023_SOURCE,
            "paygov": IRS_FORM_1023_PAYGOV,
            "schedule_flags": detect_schedule_flags(facts),
        },
        "master_writer_single_voice": True,
        "grant_quality_reviewer_can_rewrite": False,
        "readiness_officer_can_rewrite": False,
        "human_review_required": True,
        "external_submission_enabled": False,
        "safe_to_submit": False,
    }


def run_application_answer(
    *,
    dossier: str,
    question: str,
    max_words: int | None = None,
    section_type: str = "general",
    funder_archetype: str = "general",
) -> dict[str, Any]:
    result = run_single_voice_pipeline(
        dossier=dossier,
        question=question,
        facts=_facts(),
        max_words=max_words,
        section_type=section_type,
        funder_archetype=funder_archetype,
    )
    return result.to_dict()


def _irs_dossier(facts: list[dict[str, Any]]) -> str:
    lines = [
        "APPLICATION: IRS Form 1023, Application for Recognition of Exemption Under Section 501(c)(3)",
        f"OFFICIAL INSTRUCTIONS: {IRS_FORM_1023_SOURCE}",
        f"FORM REVISION: {IRS_FORM_1023_REVISION}",
        f"PAY.GOV: {IRS_FORM_1023_PAYGOV}",
        "",
        "CANONICAL ORGANIZATION RECORD:",
    ]
    for fact in facts:
        lines.append(
            f"- [{fact.get('verification_state', '')}] {fact.get('category', 'general')}.{fact.get('fact_key', '')}: "
            f"{json.dumps(fact.get('value'), ensure_ascii=False, sort_keys=True, default=str)} "
            f"(source: {fact.get('source') or 'unspecified'})"
        )
    lines.extend(
        [
            "",
            "FORM CONTROL RULES:",
            "- Use verified and approved facts as facts.",
            "- Keep unverified information conditional and flag it for human confirmation.",
            "- Never guess missing legal, financial, governance, compensation, signature, or filing information.",
            "- This workflow prepares and reviews Form 1023; it never signs, pays, certifies, or submits the filing.",
        ]
    )
    return "\n".join(lines)


def build_irs1023_production_packet(
    *,
    generate_ai: bool = True,
    question_ids: list[str] | None = None,
) -> dict[str, Any]:
    facts = _facts()
    index = _fact_index(facts)
    fields: list[ReviewField] = []
    missing: list[str] = []

    for label, key in STATIC_FIELDS:
        field = _static_field(key, index)
        fields.append(
            ReviewField(
                label=label,
                value=field.value,
                source=field.source,
                requires_user_confirmation=field.requires_user_confirmation,
            )
        )
        if not field.value:
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
    if schedule_flags.get("F") != "POTENTIALLY_REQUIRED":
        selected = [question for question in selected if question.question_id != "SCHEDULE-F"]

    results: list[dict[str, Any]] = []
    if generate_ai:
        dossier = _irs_dossier(facts)
        for question in selected:
            result = run_single_voice_pipeline(
                dossier=dossier,
                question=f"{question.part} — {question.label}\n\n{question.prompt}",
                facts=facts,
                max_words=question.max_words,
                section_type=question.section,
                funder_archetype="government",
            )
            item = result.to_dict()
            item["question"] = question.to_dict()
            results.append(item)
            fields.append(
                ReviewField(
                    label=f"{question.part} — {question.label}",
                    value=result.final_answer,
                    source=f"GrantBot v29 production artifact {result.artifact_sha256}",
                    requires_user_confirmation=True,
                )
            )
            if result.status != "READY_FOR_HUMAN_REVIEW" or not result.final_answer:
                missing.append(f"Remediate {question.question_id}")
            else:
                missing.append(f"Review and approve {question.question_id}")

    notes = [
        f"Official IRS instructions: {IRS_FORM_1023_SOURCE}",
        f"Form revision: {IRS_FORM_1023_REVISION}",
        "GrantBot v29 uses specialist AI internally but only the Broken Growth Master Grant Writer authors applicant-facing prose.",
        "The Independent Grant Quality and Compliance Reviewer critiques only; it cannot rewrite the answer.",
        "The Application Readiness Officer returns verdicts/checklists only; it cannot rewrite the answer.",
        "Every generated answer remains human-review required.",
        "GrantBot does not sign, certify, pay, or submit the IRS application.",
        *(f"Schedule {letter}: {state}" for letter, state in schedule_flags.items()),
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
            "Review all Master Writer narratives against canonical facts and official source documents.",
            "Confirm which Form 1023 schedules A-H apply.",
            "Assemble organizing document, amendments, bylaws, and required supplemental responses into the required attachment package.",
            "Verify current Pay.gov attachment and formatting requirements before filing.",
            "Have an authorized officer review the complete application.",
            "Enter only human-approved answers into Pay.gov.",
            "Authorized human signer certifies, pays the user fee, and submits the application.",
            "Store the Pay.gov/IRS receipt in GrantBot after filing.",
        ],
        notes=notes,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    folder = save_review_packet(packet)
    return {
        "packet": packet.to_dict(),
        "folder": str(folder),
        "answers": results,
        "schedule_flags": schedule_flags,
        "human_review_required": True,
        "submission_performed": False,
        "safe_to_submit": False,
    }
