from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from grantbot.agents.crewai_multimodel import resolve_role_runtime
from grantbot.agents.crewai_runtime import CrewRuntime, _build_llm, _readiness_status
from grantbot.claims.checker import check_claims
from grantbot.learning.review_learning import approved_examples, learning_profile
from grantbot.writing.quality_gate import evaluate_draft
from grantbot.writing.voice_contract import render_voice_contract, voice_integrity_issues


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STAGING_DIR = PROJECT_ROOT / "data" / "production_staging_v29"
ORCHESTRATION_MODE = "crewai-specialists->single-master-writer->quality-review->same-writer-revision->readiness->deterministic-gates"

ROLE_ORDER = (
    "research",
    "eligibility",
    "strategy",
    "writing",
    "grant_quality",
    "readiness",
)

LEGACY_ROLE_MAP = {
    "research": "research",
    "eligibility": "eligibility",
    "strategy": "strategy",
    "writing": "writing",
    "grant_quality": "red_team",
    "readiness": "readiness",
}


@dataclass(frozen=True, slots=True)
class SingleVoiceResult:
    status: str
    final_answer: str | None
    role_models: dict[str, dict[str, Any]]
    deterministic_quality: dict[str, Any]
    claim_integrity: dict[str, Any]
    voice_integrity: dict[str, Any]
    readiness_output: str
    artifact_path: str
    artifact_sha256: str
    orchestration: str = ORCHESTRATION_MODE
    master_writer_reused_for_revision: bool = True
    human_review_required: bool = True
    submission_performed: bool = False
    safe_to_submit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_single_voice_plan() -> dict[str, CrewRuntime]:
    return {
        role: resolve_role_runtime(LEGACY_ROLE_MAP[role])
        for role in ROLE_ORDER
    }


def single_voice_status() -> dict[str, Any]:
    plan = resolve_single_voice_plan()
    return {
        "available": all(runtime.available for runtime in plan.values()),
        "version": "29.0.0",
        "orchestration": ORCHESTRATION_MODE,
        "master_writer_reused_for_revision": True,
        "reviewer_can_rewrite_final_prose": False,
        "readiness_can_rewrite_final_prose": False,
        "roles": {
            role: {
                "available": runtime.available,
                "provider": runtime.provider,
                "model": runtime.model,
                "mode": runtime.mode,
                "reason": runtime.reason,
            }
            for role, runtime in plan.items()
        },
        "human_review_required": True,
        "submission_performed": False,
        "safe_to_submit": False,
    }


def _load_crewai():
    try:
        from crewai import Agent, Crew, Process, Task
    except ImportError as exc:
        raise RuntimeError(
            "CrewAI is not installed. Install GrantBot with: python -m pip install -e '.[agents]'"
        ) from exc
    return Agent, Crew, Process, Task


def _role_models(plan: Mapping[str, CrewRuntime]) -> dict[str, dict[str, Any]]:
    return {
        role: {
            "provider": runtime.provider,
            "model": runtime.model,
            "mode": runtime.mode,
        }
        for role, runtime in plan.items()
    }


def _normalize_fact(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(raw.get("fact_id", raw.get("id", ""))).strip(),
        "key": str(raw.get("fact_key", raw.get("key", ""))).strip(),
        "fact_key": str(raw.get("fact_key", raw.get("key", ""))).strip(),
        "category": str(raw.get("category", "general")).strip(),
        "value": raw.get("value", raw.get("answer")),
        "status": str(raw.get("verification_state", raw.get("status", "APPROVED"))).strip().upper(),
        "source": str(raw.get("source", "")).strip(),
    }


def _fact_block(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return "(no canonical organization facts supplied)"
    lines: list[str] = []
    for raw in facts:
        fact = _normalize_fact(raw)
        lines.append(
            f"- [{fact['status']}] {fact['category']}.{fact['key']}: "
            f"{json.dumps(fact['value'], ensure_ascii=False, sort_keys=True, default=str)} "
            f"(source: {fact['source'] or 'unspecified'})"
        )
    return "\n".join(lines)


def _style_memory(question: str, section_type: str, funder_archetype: str) -> str:
    try:
        examples = approved_examples(
            query=question,
            section_type=section_type,
            funder_archetype=funder_archetype,
            limit=3,
        )
        profile = learning_profile(
            section_type=section_type,
            funder_archetype=funder_archetype,
        )
    except Exception:
        examples = []
        profile = {}

    blocks = [
        "HUMAN-APPROVED WRITING MEMORY — STYLE AND STRUCTURE ONLY; NEVER FACTUAL EVIDENCE:",
    ]
    if not examples:
        blocks.append("(none yet)")
    else:
        for index, item in enumerate(examples, start=1):
            text = str(item.get("final_text", "")).strip()
            if len(text) > 3500:
                text = text[:3500].rstrip() + " [truncated]"
            blocks.extend(
                [
                    f"REFERENCE {index}",
                    f"Reviewer score: {item.get('reviewer_score', 'unknown')}",
                    text,
                ]
            )
    blocks.extend(
        [
            "",
            "HUMAN REVIEW PREFERENCE PROFILE:",
            json.dumps(profile, ensure_ascii=False, sort_keys=True, default=str),
        ]
    )
    return "\n".join(blocks)


def _task_text(result: Any, index: int, label: str) -> str:
    outputs = getattr(result, "tasks_output", None)
    if not isinstance(outputs, (list, tuple)) or len(outputs) <= index:
        raise RuntimeError(f"CrewAI did not expose required task output: {label}")
    item = outputs[index]
    raw = getattr(item, "raw", None)
    text = str(raw if raw is not None else item).strip()
    if not text:
        raise RuntimeError(f"CrewAI returned empty task output: {label}")
    return text


def build_single_voice_crew(
    *,
    question: str,
    section_type: str = "general",
    funder_archetype: str = "general",
):
    Agent, Crew, Process, Task = _load_crewai()
    plan = resolve_single_voice_plan()
    unavailable = [role for role, runtime in plan.items() if not runtime.available or not runtime.model]
    if unavailable:
        detail = "; ".join(
            f"{role}: {plan[role].reason or 'unavailable'}"
            for role in unavailable
        )
        raise RuntimeError(f"Single-voice production AI plan is incomplete: {detail}")

    llms = {role: _build_llm(runtime) for role, runtime in plan.items()}
    voice_contract = render_voice_contract()
    style_memory = _style_memory(question, section_type, funder_archetype)
    integrity = (
        "Never invent facts, statistics, budgets, dates, outcomes, partnerships, legal status, "
        "certifications, signatures, approvals, payments, awards, or submission status. Unknowns stay unknown. "
        "No AI role may sign, certify, pay, authorize, or submit an application."
    )

    researcher = Agent(
        role="Funding Evidence Research Director",
        goal="Extract decision-relevant evidence, requirements, source facts, dates, and unknowns with provenance.",
        backstory="You are a doctoral nonprofit funding researcher. " + integrity,
        llm=llms["research"],
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )
    eligibility = Agent(
        role="Eligibility and Compliance Director",
        goal="Determine hard eligibility, legal and tax constraints, certifications, attachments, and unresolved gates.",
        backstory="You are a nonprofit and public-funding compliance specialist. " + integrity,
        llm=llms["eligibility"],
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )
    strategist = Agent(
        role="Grant Strategy and Program Architecture Director",
        goal="Build the strongest truthful response strategy from verified evidence and compliance constraints.",
        backstory="You specialize in nonprofit strategy, housing, homelessness, reentry, workforce, and community development. " + integrity,
        llm=llms["strategy"],
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )
    writer = Agent(
        role="Broken Growth Master Grant Writer",
        goal="Own every sentence of applicant-facing prose and preserve one consistent voice across draft and revision.",
        backstory=(
            "You are the sole author of final applicant-facing prose. Other specialists may provide evidence, strategy, "
            "and critique, but only you write or revise the answer.\n\n" + voice_contract + "\n\n" + style_memory + "\n\n" + integrity
        ),
        llm=llms["writing"],
        verbose=False,
        allow_delegation=False,
        max_iter=8,
    )
    quality_reviewer = Agent(
        role="Independent Grant Quality and Compliance Reviewer",
        goal="Evaluate the draft for factual support, compliance, completeness, clarity, persuasion, and reviewer risk without rewriting it.",
        backstory=(
            "You are a skeptical grant-panel and compliance reviewer. Return findings and revision instructions only. "
            "Never provide replacement prose, rewritten paragraphs, or a substitute final answer. " + integrity
        ),
        llm=llms["grant_quality"],
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )
    readiness = Agent(
        role="Application Readiness Officer",
        goal="Issue a fail-closed readiness verdict after reviewing the final Master Writer revision.",
        backstory=(
            "You are the last AI control before mandatory human review. You may only issue a verdict and checklist. "
            "Never rewrite, paraphrase, or replace the Master Writer's final answer. " + integrity
        ),
        llm=llms["readiness"],
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )

    research_task = Task(
        description=(
            "Analyze the application dossier and canonical fact record. Extract source-backed facts, requirements, "
            "deadlines, eligibility language, financial constraints, missing information, and human-confirmation items. "
            "Do not write applicant-facing prose.\n\nDOSSIER:\n{dossier}\n\nCANONICAL FACTS:\n{facts_block}"
        ),
        expected_output="Evidence brief separating supported facts, planning context, source requirements, and unknowns.",
        agent=researcher,
    )
    eligibility_task = Task(
        description=(
            "Audit the evidence brief against the application requirements. Classify each material gate as CONFIRMED, "
            "CONDITIONAL, UNKNOWN, or BLOCKED. Identify certifications, attachments, legal/tax restrictions, and human-only decisions. "
            "Do not write applicant-facing prose."
        ),
        expected_output="Eligibility and compliance memorandum with explicit blockers and unresolved items.",
        agent=eligibility,
        context=[research_task],
    )
    strategy_task = Task(
        description=(
            "Develop the strongest truthful response strategy for this exact question: {question}. Use evidence and compliance constraints. "
            "Specify the argument order, facts to emphasize, planning statements that must remain prospective, and likely reviewer concerns. "
            "Do not write the final answer."
        ),
        expected_output="Answer strategy and outline for the Master Writer.",
        agent=strategist,
        context=[research_task, eligibility_task],
    )
    draft_task = Task(
        description=(
            "Write the applicant-facing answer to: {question}. Stay within {max_words} words when positive. "
            "Follow your permanent Broken Growth voice contract. Use only supported facts and clearly prospective planning context. "
            "Return only the draft answer, with no internal labels or commentary."
        ),
        expected_output="Single-voice applicant-facing draft answer only.",
        agent=writer,
        context=[research_task, eligibility_task, strategy_task],
    )
    review_task = Task(
        description=(
            "Review the Master Writer draft against the evidence, compliance memo, strategy, exact question, and requirements. "
            "Score factual support, requirement coverage, directness, clarity, persuasion, consistency, and risk. "
            "Return only critique and exact revision instructions. DO NOT write replacement prose and DO NOT rewrite any paragraph."
        ),
        expected_output="Grant quality review with severity-ranked findings and revision instructions only.",
        agent=quality_reviewer,
        context=[research_task, eligibility_task, strategy_task, draft_task],
    )
    revision_task = Task(
        description=(
            "Revise YOUR OWN draft using the independent review instructions. You remain the sole author. Preserve the same voice, terminology, "
            "and factual discipline. Correct every supported issue without importing reviewer wording as final prose. Stay within {max_words} words when positive. "
            "Return only the final applicant-facing answer."
        ),
        expected_output="Final single-voice applicant-facing answer only.",
        agent=writer,
        context=[research_task, eligibility_task, strategy_task, draft_task, review_task],
    )
    readiness_task = Task(
        description=(
            "Review the final Master Writer revision. First line must be exactly READINESS=READY_FOR_HUMAN_REVIEW or READINESS=REMEDIATION_REQUIRED. "
            "After the first line list unresolved facts, compliance blockers, missing attachments, human-only decisions, signatures/certifications, and next actions. "
            "DO NOT reproduce, paraphrase, edit, or replace the final answer. Never return SUBMITTED or APPROVED_FOR_SUBMISSION."
        ),
        expected_output="Readiness verdict and human-review/remediation checklist only; no applicant-facing prose.",
        agent=readiness,
        context=[research_task, eligibility_task, strategy_task, revision_task, review_task],
    )

    crew = Crew(
        agents=[researcher, eligibility, strategist, writer, quality_reviewer, readiness],
        tasks=[research_task, eligibility_task, strategy_task, draft_task, review_task, revision_task, readiness_task],
        process=Process.sequential,
        verbose=False,
    )
    return plan, crew


def _deterministic_checks(
    *,
    question: str,
    final_answer: str,
    facts: list[dict[str, Any]],
    dossier: str,
    max_words: int | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    normalized = [_normalize_fact(item) for item in facts]
    source_records = list(normalized)
    source_records.append(
        {
            "id": "application-dossier",
            "key": "application_dossier",
            "fact_key": "application_dossier",
            "category": "external_source",
            "value": dossier,
            "status": "VERIFIED",
            "source": "current application dossier",
        }
    )
    quality = evaluate_draft(
        question=question,
        draft=final_answer,
        facts=source_records,
        max_words=max_words,
    ).to_dict()
    claims = check_claims(final_answer, source_records)
    voice_issues = voice_integrity_issues(final_answer)
    voice = {"passed": not voice_issues, "issues": voice_issues}
    return quality, claims, voice


def _stage(
    *,
    plan: Mapping[str, CrewRuntime],
    dossier: str,
    question: str,
    max_words: int | None,
    final_answer: str,
    draft_answer: str,
    review_output: str,
    readiness_output: str,
    quality: dict[str, Any],
    claims: dict[str, Any],
    voice: dict[str, Any],
    status: str,
    staging_dir: Path = DEFAULT_STAGING_DIR,
) -> tuple[str, str]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone()
    record = {
        "version": "29.0.0",
        "created_at": timestamp.isoformat(),
        "orchestration": ORCHESTRATION_MODE,
        "role_models": _role_models(plan),
        "question": question,
        "max_words": max_words,
        "dossier_sha256": hashlib.sha256(dossier.encode("utf-8")).hexdigest(),
        "draft_answer": draft_answer,
        "final_answer": final_answer,
        "final_answer_sha256": hashlib.sha256(final_answer.encode("utf-8")).hexdigest(),
        "grant_quality_review": review_output,
        "readiness_output": readiness_output,
        "deterministic_quality": quality,
        "claim_integrity": claims,
        "voice_integrity": voice,
        "status": status,
        "master_writer_reused_for_revision": True,
        "reviewer_can_rewrite_final_prose": False,
        "readiness_can_rewrite_final_prose": False,
        "human_review_required": True,
        "external_side_effects_performed": False,
        "submission_performed": False,
        "safe_to_submit": False,
    }
    destination = staging_dir / (
        "production_run_" + timestamp.strftime("%Y%m%d_%H%M%S_%f") + ".json"
    )
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(destination)
    destination.chmod(0o600)
    return str(destination), hashlib.sha256(destination.read_bytes()).hexdigest()


def run_single_voice_pipeline(
    *,
    dossier: str,
    question: str,
    facts: list[dict[str, Any]],
    max_words: int | None = None,
    section_type: str = "general",
    funder_archetype: str = "general",
) -> SingleVoiceResult:
    if not dossier.strip():
        raise ValueError("dossier cannot be empty")
    if not question.strip():
        raise ValueError("question cannot be empty")
    if max_words is not None and max_words <= 0:
        raise ValueError("max_words must be positive when supplied")

    plan, crew = build_single_voice_crew(
        question=question,
        section_type=section_type,
        funder_archetype=funder_archetype,
    )
    result = crew.kickoff(
        inputs={
            "dossier": dossier,
            "question": question,
            "max_words": max_words if max_words is not None else 0,
            "facts_block": _fact_block(facts),
        }
    )

    draft_answer = _task_text(result, 3, "master writer draft")
    review_output = _task_text(result, 4, "grant quality review")
    final_answer = _task_text(result, 5, "master writer revision")
    readiness_output = _task_text(result, 6, "application readiness")

    quality, claims, voice = _deterministic_checks(
        question=question,
        final_answer=final_answer,
        facts=facts,
        dossier=dossier,
        max_words=max_words,
    )
    ai_status = _readiness_status(readiness_output)
    deterministic_pass = bool(quality.get("passed")) and bool(claims.get("safe")) and bool(voice.get("passed"))
    status = "READY_FOR_HUMAN_REVIEW" if ai_status == "READY_FOR_HUMAN_REVIEW" and deterministic_pass else "REMEDIATION_REQUIRED"

    artifact_path, artifact_sha256 = _stage(
        plan=plan,
        dossier=dossier,
        question=question,
        max_words=max_words,
        final_answer=final_answer,
        draft_answer=draft_answer,
        review_output=review_output,
        readiness_output=readiness_output,
        quality=quality,
        claims=claims,
        voice=voice,
        status=status,
    )

    return SingleVoiceResult(
        status=status,
        final_answer=final_answer,
        role_models=_role_models(plan),
        deterministic_quality=quality,
        claim_integrity=claims,
        voice_integrity=voice,
        readiness_output=readiness_output,
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
    )
