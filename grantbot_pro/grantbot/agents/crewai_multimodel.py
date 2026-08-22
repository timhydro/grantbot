from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from grantbot.agents.crewai_runtime import (
    CrewRuntime,
    _build_llm,
    _readiness_status,
    resolve_runtime,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STAGING_DIR = PROJECT_ROOT / "data" / "crewai_staging"
ORCHESTRATION_MODE = "crewai-multi-model->specialist-crew->deterministic-staging"
ROLE_ORDER = (
    "research",
    "eligibility",
    "strategy",
    "writing",
    "red_team",
    "readiness",
)

ROLE_ENV_VARS = {
    "research": "GRANTBOT_CREWAI_RESEARCH_MODEL",
    "eligibility": "GRANTBOT_CREWAI_ELIGIBILITY_MODEL",
    "strategy": "GRANTBOT_CREWAI_STRATEGY_MODEL",
    "writing": "GRANTBOT_CREWAI_WRITING_MODEL",
    "red_team": "GRANTBOT_CREWAI_REVIEW_MODEL",
    "readiness": "GRANTBOT_CREWAI_READINESS_MODEL",
}

ROLE_TEMPERATURES = {
    "research": 0.05,
    "eligibility": 0.05,
    "strategy": 0.20,
    "writing": 0.30,
    "red_team": 0.05,
    "readiness": 0.00,
}


@dataclass(frozen=True, slots=True)
class RoleRuntime:
    role: str
    provider: str
    model: str
    base_url: str | None
    mode: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MultiModelRunResult:
    output: str
    role_models: dict[str, dict[str, Any]]
    artifact_path: str
    artifact_sha256: str
    status: str
    orchestration: str = ORCHESTRATION_MODE
    human_review_required: bool = True
    submission_performed: bool = False
    safe_to_submit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _candidate_models(role: str, env: Mapping[str, str]) -> list[str]:
    if role not in ROLE_ORDER:
        raise ValueError(f"Unknown CrewAI role: {role}")

    explicit = str(env.get(ROLE_ENV_VARS[role], "")).strip()
    if explicit:
        return [explicit]

    candidates: list[str] = []
    metered = _truthy(env.get("GRANTBOT_ALLOW_METERED_AI"))

    if metered:
        xai_model = str(env.get("GRANTBOT_XAI_MODEL", "")).strip()
        if role in {"strategy", "writing"} and env.get("XAI_API_KEY", "").strip() and xai_model.startswith("xai/"):
            candidates.append(xai_model)

        role_priority = {
            "research": (
                ("CEREBRAS_API_KEY", "cerebras/gpt-oss-120b"),
                ("GROQ_API_KEY", "groq/openai/gpt-oss-120b"),
                ("GEMINI_API_KEY", "gemini/gemini-2.5-flash"),
            ),
            "eligibility": (
                ("GEMINI_API_KEY", "gemini/gemini-2.5-flash"),
                ("GROQ_API_KEY", "groq/openai/gpt-oss-120b"),
                ("MISTRAL_API_KEY", "mistral/mistral-large-latest"),
            ),
            "strategy": (
                ("GEMINI_API_KEY", "gemini/gemini-2.5-flash"),
                ("MISTRAL_API_KEY", "mistral/mistral-large-latest"),
                ("GROQ_API_KEY", "groq/openai/gpt-oss-120b"),
            ),
            "writing": (
                ("MISTRAL_API_KEY", "mistral/mistral-large-latest"),
                ("GEMINI_API_KEY", "gemini/gemini-2.5-flash"),
                ("GROQ_API_KEY", "groq/openai/gpt-oss-120b"),
            ),
            "red_team": (
                ("GEMINI_API_KEY", "gemini/gemini-2.5-flash"),
                ("CEREBRAS_API_KEY", "cerebras/gpt-oss-120b"),
                ("GROQ_API_KEY", "groq/openai/gpt-oss-120b"),
            ),
            "readiness": (
                ("GROQ_API_KEY", "groq/openai/gpt-oss-120b"),
                ("GEMINI_API_KEY", "gemini/gemini-2.5-flash"),
                ("CEREBRAS_API_KEY", "cerebras/gpt-oss-120b"),
            ),
        }
        for key_name, model in role_priority[role]:
            if env.get(key_name, "").strip():
                candidates.append(model)

    if env.get("OPENROUTER_API_KEY", "").strip():
        candidates.append("openrouter/openrouter/free")

    global_model = str(env.get("GRANTBOT_CREWAI_MODEL", "")).strip()
    if global_model:
        candidates.append(global_model)

    return list(dict.fromkeys(candidates))


def resolve_role_runtime(
    role: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> CrewRuntime:
    env = dict(environment or os.environ)
    attempted: list[str] = []

    for model in _candidate_models(role, env):
        attempted.append(model)
        runtime = resolve_runtime(model=model)
        if runtime.available and runtime.model:
            return CrewRuntime(
                available=True,
                provider=runtime.provider,
                model=runtime.model,
                base_url=runtime.base_url,
                mode=f"role:{role}:{runtime.mode}",
            )

    fallback = resolve_runtime()
    if fallback.available and fallback.model:
        return CrewRuntime(
            available=True,
            provider=fallback.provider,
            model=fallback.model,
            base_url=fallback.base_url,
            mode=f"role:{role}:fallback:{fallback.mode}",
        )

    attempted_text = ", ".join(attempted) if attempted else "no role-specific candidates"
    return CrewRuntime(
        available=False,
        provider="none",
        model=None,
        base_url=None,
        mode=f"role:{role}:unavailable",
        reason=f"No usable model for role {role}; attempted {attempted_text}. {fallback.reason or ''}".strip(),
    )


def resolve_role_plan(
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, CrewRuntime]:
    env = dict(environment or os.environ)
    return {
        role: resolve_role_runtime(role, environment=env)
        for role in ROLE_ORDER
    }


def role_plan_status(
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    plan = resolve_role_plan(environment=environment)
    return {
        "available": all(runtime.available for runtime in plan.values()),
        "orchestration": ORCHESTRATION_MODE,
        "metered_ai_enabled": _truthy((environment or os.environ).get("GRANTBOT_ALLOW_METERED_AI")),
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


def _llms_for_plan(plan: Mapping[str, CrewRuntime]) -> dict[str, Any]:
    llms: dict[str, Any] = {}
    for role in ROLE_ORDER:
        runtime = plan[role]
        if not runtime.available or not runtime.model:
            raise RuntimeError(runtime.reason or f"No model available for role {role}")
        llm = _build_llm(runtime)
        try:
            llm.temperature = ROLE_TEMPERATURES[role]
        except Exception:
            pass
        llms[role] = llm
    return llms


def build_multimodel_grant_crew():
    try:
        from crewai import Agent, Crew, Process, Task
    except ImportError as exc:
        raise RuntimeError(
            "CrewAI is not installed. Install GrantBot with: python -m pip install -e '.[agents]'"
        ) from exc

    plan = resolve_role_plan()
    unavailable = [role for role, runtime in plan.items() if not runtime.available]
    if unavailable:
        details = "; ".join(
            f"{role}: {plan[role].reason or 'unavailable'}"
            for role in unavailable
        )
        raise RuntimeError(f"Multi-model CrewAI plan is incomplete: {details}")

    llms = _llms_for_plan(plan)
    integrity_rule = (
        "Never invent eligibility, statistics, budgets, partnerships, approvals, signatures, "
        "commitments, outcomes, legal status, financial data, or submission status. "
        "Unknowns remain unknown. No agent may submit, sign, certify, or authorize a filing."
    )

    researcher = Agent(
        role="Funding Evidence Research Director",
        goal="Extract source-grounded facts, requirements, dates, evidence, and unknowns with provenance.",
        backstory="You are a doctoral nonprofit research specialist. " + integrity_rule,
        llm=llms["research"],
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )
    eligibility = Agent(
        role="Eligibility and Compliance Counsel",
        goal="Determine hard eligibility, tax/legal constraints, required certifications, and unresolved gates.",
        backstory="You are an adversarial nonprofit and government-funding compliance specialist. " + integrity_rule,
        llm=llms["eligibility"],
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )
    strategist = Agent(
        role="Grant Strategy and Program Architecture Director",
        goal="Turn verified evidence and constraints into the strongest lawful response strategy.",
        backstory="You specialize in reentry, housing, homelessness, workforce, and public-benefit program design. " + integrity_rule,
        llm=llms["strategy"],
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )
    writer = Agent(
        role="Senior Persuasive Grant and Application Writer",
        goal="Produce precise, compelling, question-specific prose grounded only in supported facts and clearly labeled plans.",
        backstory="You write at doctoral professional quality with strong ethos, pathos, logos, specificity, and restraint. " + integrity_rule,
        llm=llms["writing"],
        verbose=False,
        allow_delegation=False,
        max_iter=8,
    )
    red_team = Agent(
        role="Independent Red-Team Reviewer",
        goal="Attack the draft for unsupported claims, omissions, contradictions, compliance risk, and weak reasoning.",
        backstory="You review as a skeptical regulator and funding panelist. " + integrity_rule,
        llm=llms["red_team"],
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )
    readiness = Agent(
        role="Submission Readiness Officer",
        goal="Issue a fail-closed staging verdict and enumerate every unresolved human-only item.",
        backstory="You are the final AI gate before mandatory human review. " + integrity_rule,
        llm=llms["readiness"],
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )

    research_task = Task(
        description=(
            "Analyze this application dossier. Extract source facts, eligibility language, dates, "
            "financial constraints, required documents, unresolved facts, and human-confirmation items. "
            "Dossier:\n{dossier}"
        ),
        expected_output="Evidence brief with verified facts, planning context, unknowns, and provenance.",
        agent=researcher,
    )
    eligibility_task = Task(
        description=(
            "Audit the evidence brief for legal, tax, applicant, financial, certification, attachment, "
            "and submission requirements. Mark each gate CONFIRMED, CONDITIONAL, UNKNOWN, or BLOCKED."
        ),
        expected_output="Eligibility and compliance memorandum with explicit blockers and human-only decisions.",
        agent=eligibility,
        context=[research_task],
    )
    strategy_task = Task(
        description=(
            "Using the evidence and compliance memorandum, design the strongest truthful answer strategy "
            "for the exact question. Separate facts, projections, and missing information."
        ),
        expected_output="Decision-ready answer strategy and outline.",
        agent=strategist,
        context=[research_task, eligibility_task],
    )
    writing_task = Task(
        description=(
            "Answer this exact application question: {question}. Stay within {max_words} words when positive. "
            "Use only evidence and clearly prospective planning context. Do not invent facts."
        ),
        expected_output="Submission-quality draft answer.",
        agent=writer,
        context=[research_task, eligibility_task, strategy_task],
    )
    red_team_task = Task(
        description=(
            "Red-team the draft against the evidence, compliance memo, strategy, and exact question. "
            "Identify unsupported claims, missing facts, contradictions, weak language, and compliance risks. "
            "Then state exact corrections required."
        ),
        expected_output="Severity-ranked adversarial review and required corrections.",
        agent=red_team,
        context=[research_task, eligibility_task, strategy_task, writing_task],
    )
    readiness_task = Task(
        description=(
            "Review all prior work. First line must be exactly "
            "READINESS=READY_FOR_HUMAN_REVIEW or READINESS=REMEDIATION_REQUIRED. "
            "Then write FINAL_ANSWER_BEGIN on its own line, the corrected final answer, and "
            "FINAL_ANSWER_END on its own line. After that list unresolved facts, human-only decisions, "
            "signatures/certifications, and required next actions. Never return SUBMITTED or APPROVED_FOR_SUBMISSION."
        ),
        expected_output="Fail-closed readiness verdict, corrected answer, and human-review checklist.",
        agent=readiness,
        context=[research_task, eligibility_task, strategy_task, writing_task, red_team_task],
    )

    return plan, Crew(
        agents=[researcher, eligibility, strategist, writer, red_team, readiness],
        tasks=[
            research_task,
            eligibility_task,
            strategy_task,
            writing_task,
            red_team_task,
            readiness_task,
        ],
        process=Process.sequential,
        verbose=False,
    )


def extract_final_answer(output: str) -> str | None:
    start_marker = "FINAL_ANSWER_BEGIN"
    end_marker = "FINAL_ANSWER_END"
    if start_marker not in output or end_marker not in output:
        return None
    after = output.split(start_marker, 1)[1]
    body = after.split(end_marker, 1)[0].strip()
    return body or None


def run_multimodel_grant_crew_raw(
    *,
    dossier: str,
    question: str,
    max_words: int | None = None,
) -> tuple[dict[str, CrewRuntime], str]:
    if not dossier.strip():
        raise ValueError("dossier cannot be empty")
    if not question.strip():
        raise ValueError("question cannot be empty")
    if max_words is not None and max_words <= 0:
        raise ValueError("max_words must be positive when supplied")

    plan, crew = build_multimodel_grant_crew()
    result = crew.kickoff(
        inputs={
            "dossier": dossier,
            "question": question,
            "max_words": max_words if max_words is not None else 0,
        }
    )
    raw = getattr(result, "raw", None)
    output = str(raw if raw is not None else result).strip()
    if not output:
        raise RuntimeError("Multi-model CrewAI returned empty output")
    return plan, output


def _stage_multimodel_result(
    *,
    plan: Mapping[str, CrewRuntime],
    dossier: str,
    question: str,
    max_words: int | None,
    output: str,
    staging_dir: Path = DEFAULT_STAGING_DIR,
) -> tuple[str, str]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone()
    status = _readiness_status(output)
    role_models = {
        role: {
            "provider": runtime.provider,
            "model": runtime.model,
            "mode": runtime.mode,
        }
        for role, runtime in plan.items()
    }
    record = {
        "created_at": timestamp.isoformat(),
        "orchestration": ORCHESTRATION_MODE,
        "role_models": role_models,
        "question": question,
        "max_words": max_words,
        "dossier_sha256": hashlib.sha256(dossier.encode("utf-8")).hexdigest(),
        "output": output,
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "status": status,
        "human_review_required": True,
        "external_side_effects_performed": False,
        "submission_performed": False,
        "safe_to_submit": False,
    }
    destination = staging_dir / (
        "multi_model_run_" + timestamp.strftime("%Y%m%d_%H%M%S_%f") + ".json"
    )
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(destination)
    destination.chmod(0o600)
    return str(destination), hashlib.sha256(destination.read_bytes()).hexdigest()


def kickoff_multimodel_grant_crew(
    *,
    dossier: str,
    question: str,
    max_words: int | None = None,
) -> MultiModelRunResult:
    plan, output = run_multimodel_grant_crew_raw(
        dossier=dossier,
        question=question,
        max_words=max_words,
    )
    path, receipt = _stage_multimodel_result(
        plan=plan,
        dossier=dossier,
        question=question,
        max_words=max_words,
        output=output,
    )
    return MultiModelRunResult(
        output=output,
        role_models={
            role: {
                "provider": runtime.provider,
                "model": runtime.model,
                "mode": runtime.mode,
            }
            for role, runtime in plan.items()
        },
        artifact_path=path,
        artifact_sha256=receipt,
        status=_readiness_status(output),
    )
