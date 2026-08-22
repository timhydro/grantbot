from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from grantbot.writing.ollama_provider import OllamaConfig, OllamaProvider


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STAGING_DIR = PROJECT_ROOT / "data" / "crewai_staging"
ORCHESTRATION_MODE = "crewai-flow->specialist-crew->deterministic-staging"
AGENT_COUNT = 6

_PROVIDER_KEYS: dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "xai": "XAI_API_KEY",
}

_AUTOMATIC_METERED_MODELS: tuple[tuple[str, str, str], ...] = (
    ("groq", "GROQ_API_KEY", "groq/openai/gpt-oss-120b"),
    ("gemini", "GEMINI_API_KEY", "gemini/gemini-2.5-flash"),
    ("mistral", "MISTRAL_API_KEY", "mistral/mistral-large-latest"),
    ("cerebras", "CEREBRAS_API_KEY", "cerebras/gpt-oss-120b"),
)


@dataclass(frozen=True, slots=True)
class CrewRuntime:
    available: bool
    provider: str
    model: str | None
    base_url: str | None
    mode: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CrewAIStatus:
    installed: bool
    available: bool
    provider: str
    model: str | None
    base_url: str | None
    mode: str
    orchestration: str
    agent_count: int
    staging_enabled: bool
    external_side_effects_enabled: bool
    metered_ai_enabled: bool
    safe_to_submit: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CrewRunResult:
    output: str
    provider: str
    model: str
    artifact_path: str
    artifact_sha256: str
    status: str = "READY_FOR_HUMAN_REVIEW"
    orchestration: str = ORCHESTRATION_MODE
    safe_to_submit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def crewai_installed() -> bool:
    return importlib.util.find_spec("crewai") is not None


def _model_provider(model: str) -> str:
    return model.split("/", 1)[0].strip().lower() if "/" in model else ""


def _is_openrouter_free(model: str) -> bool:
    return model.strip().lower() == "openrouter/openrouter/free"


def _ollama_matches(requested: str, installed: str) -> bool:
    requested = requested.strip()
    installed = installed.strip()
    if requested == installed:
        return True
    if ":" not in requested and installed.startswith(requested + ":"):
        return True
    return False


def _validated_ollama_base_url(
    environment: Mapping[str, str],
    config: OllamaConfig,
) -> str:
    raw = (
        environment.get("GRANTBOT_CREWAI_OLLAMA_URL")
        or config.base_url
    ).strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("Configured CrewAI Ollama URL must be a valid http(s) URL")

    if not _truthy(environment.get("GRANTBOT_ALLOW_REMOTE_OLLAMA")):
        host = parsed.hostname.lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError(
                "Remote Ollama is disabled. Use loopback or explicitly set "
                "GRANTBOT_ALLOW_REMOTE_OLLAMA=1 as an operator-controlled setting."
            )
    return raw


def _select_runtime(
    *,
    environment: Mapping[str, str] | None = None,
    local_health: Mapping[str, Any] | None = None,
    model_override: str | None = None,
) -> CrewRuntime:
    env = dict(environment or os.environ)
    health = dict(local_health or {})
    explicit_model = (model_override or env.get("GRANTBOT_CREWAI_MODEL", "")).strip()
    metered_enabled = _truthy(env.get("GRANTBOT_ALLOW_METERED_AI"))

    if explicit_model:
        if explicit_model.startswith("ollama/"):
            requested = explicit_model.split("/", 1)[1].strip()
            if not requested:
                return CrewRuntime(
                    available=False,
                    provider="ollama",
                    model=explicit_model,
                    base_url=None,
                    mode="explicit-model",
                    reason="Explicit Ollama model name is empty",
                )
            if not bool(health.get("available")):
                return CrewRuntime(
                    available=False,
                    provider="ollama",
                    model=explicit_model,
                    base_url=None,
                    mode="explicit-model",
                    reason=str(health.get("error") or "Local Ollama is unavailable"),
                )
            installed = [str(item).strip() for item in health.get("installed_models", []) if str(item).strip()]
            matched = next((item for item in installed if _ollama_matches(requested, item)), None)
            if matched is None:
                return CrewRuntime(
                    available=False,
                    provider="ollama",
                    model=explicit_model,
                    base_url=None,
                    mode="explicit-model",
                    reason=f"Requested Ollama model is not installed: {requested}",
                )
            try:
                base_url = _validated_ollama_base_url(env, OllamaConfig())
            except RuntimeError as exc:
                return CrewRuntime(
                    available=False,
                    provider="ollama",
                    model=f"ollama/{matched}",
                    base_url=None,
                    mode="explicit-model",
                    reason=str(exc),
                )
            return CrewRuntime(
                available=True,
                provider="ollama",
                model=f"ollama/{matched}",
                base_url=base_url,
                mode="explicit-model",
            )

        provider = _model_provider(explicit_model)
        required_key = _PROVIDER_KEYS.get(provider)
        if required_key is None:
            return CrewRuntime(
                available=False,
                provider=provider or "unknown",
                model=explicit_model,
                base_url=None,
                mode="explicit-model",
                reason="Unsupported CrewAI provider; only approved GrantBot providers are allowed",
            )
        if not env.get(required_key, "").strip():
            return CrewRuntime(
                available=False,
                provider=provider,
                model=explicit_model,
                base_url=None,
                mode="explicit-model",
                reason=f"{required_key} is not loaded",
            )
        if not _is_openrouter_free(explicit_model) and not metered_enabled:
            return CrewRuntime(
                available=False,
                provider=provider,
                model=explicit_model,
                base_url=None,
                mode="explicit-model",
                reason=(
                    "Metered CrewAI models are disabled. Set GRANTBOT_ALLOW_METERED_AI=1 "
                    "as an operator-controlled setting before using this model."
                ),
            )
        return CrewRuntime(
            available=True,
            provider=provider,
            model=explicit_model,
            base_url=None,
            mode="explicit-model",
        )

    if env.get("OPENROUTER_API_KEY", "").strip():
        return CrewRuntime(
            available=True,
            provider="openrouter",
            model="openrouter/openrouter/free",
            base_url=None,
            mode="automatic-free-cloud",
        )

    if bool(health.get("available")) and str(health.get("selected_model") or "").strip():
        selected = str(health["selected_model"]).strip()
        try:
            base_url = _validated_ollama_base_url(env, OllamaConfig())
        except RuntimeError as exc:
            return CrewRuntime(
                available=False,
                provider="ollama",
                model=f"ollama/{selected}",
                base_url=None,
                mode="automatic-local",
                reason=str(exc),
            )
        return CrewRuntime(
            available=True,
            provider="ollama",
            model=f"ollama/{selected}",
            base_url=base_url,
            mode="automatic-local",
        )

    if metered_enabled:
        for provider, key_name, model in _AUTOMATIC_METERED_MODELS:
            if env.get(key_name, "").strip():
                return CrewRuntime(
                    available=True,
                    provider=provider,
                    model=model,
                    base_url=None,
                    mode="automatic-metered-cloud",
                )
        xai_model = env.get("GRANTBOT_XAI_MODEL", "").strip()
        if env.get("XAI_API_KEY", "").strip() and xai_model.startswith("xai/"):
            return CrewRuntime(
                available=True,
                provider="xai",
                model=xai_model,
                base_url=None,
                mode="automatic-metered-cloud",
            )

    return CrewRuntime(
        available=False,
        provider="none",
        model=None,
        base_url=None,
        mode="unavailable",
        reason=(
            "No cost-protected CrewAI runtime is available. Load OPENROUTER_API_KEY, "
            "start a usable local Ollama model, or explicitly enable metered AI with "
            "GRANTBOT_ALLOW_METERED_AI=1."
        ),
    )


def resolve_runtime(*, model: str | None = None) -> CrewRuntime:
    env = dict(os.environ)
    explicit_model = (model or env.get("GRANTBOT_CREWAI_MODEL", "")).strip()

    if explicit_model and not explicit_model.startswith("ollama/"):
        return _select_runtime(
            environment=env,
            local_health={},
            model_override=model,
        )

    if not explicit_model and env.get("OPENROUTER_API_KEY", "").strip():
        return _select_runtime(
            environment=env,
            local_health={},
            model_override=None,
        )

    config = OllamaConfig()
    health = OllamaProvider(config).health()
    return _select_runtime(
        environment=env,
        local_health=health,
        model_override=model,
    )


def crewai_status() -> CrewAIStatus:
    installed = crewai_installed()
    if not installed:
        return CrewAIStatus(
            installed=False,
            available=False,
            provider="none",
            model=None,
            base_url=None,
            mode="unavailable",
            orchestration=ORCHESTRATION_MODE,
            agent_count=AGENT_COUNT,
            staging_enabled=True,
            external_side_effects_enabled=False,
            metered_ai_enabled=_truthy(os.getenv("GRANTBOT_ALLOW_METERED_AI")),
            safe_to_submit=False,
            error="CrewAI is not installed",
        )

    runtime = resolve_runtime()
    return CrewAIStatus(
        installed=True,
        available=runtime.available,
        provider=runtime.provider,
        model=runtime.model,
        base_url=runtime.base_url,
        mode=runtime.mode,
        orchestration=ORCHESTRATION_MODE,
        agent_count=AGENT_COUNT,
        staging_enabled=True,
        external_side_effects_enabled=False,
        metered_ai_enabled=_truthy(os.getenv("GRANTBOT_ALLOW_METERED_AI")),
        safe_to_submit=False,
        error=None if runtime.available else runtime.reason,
    )


def _load_crewai():
    if not crewai_installed():
        raise RuntimeError(
            "CrewAI is not installed. Install GrantBot with: "
            "python -m pip install -e '.[agents]'"
        )
    from crewai import Agent, Crew, LLM, Process, Task

    return Agent, Crew, LLM, Process, Task


def _build_llm(runtime: CrewRuntime):
    _, _, LLM, _, _ = _load_crewai()
    if not runtime.model:
        raise RuntimeError("CrewAI runtime has no model")
    kwargs: dict[str, Any] = {
        "model": runtime.model,
        "temperature": 0.15,
    }
    if runtime.provider == "ollama":
        if not runtime.base_url:
            raise RuntimeError("Ollama runtime has no operator-approved base URL")
        kwargs["base_url"] = runtime.base_url
    elif runtime.base_url is not None:
        raise RuntimeError("Cloud CrewAI runtimes may not override provider base URLs")
    return LLM(**kwargs)


def build_grant_crew(*, model: str | None = None):
    Agent, Crew, _, Process, Task = _load_crewai()
    runtime = resolve_runtime(model=model)
    if not runtime.available or not runtime.model:
        raise RuntimeError(runtime.reason or "No CrewAI runtime is available")

    llm = _build_llm(runtime)
    integrity_rule = (
        "Never claim an external action occurred unless deterministic GrantBot code records a receipt. "
        "Unknown and pending facts remain unknown or pending. Never invent eligibility, statistics, budgets, "
        "partnerships, approvals, signatures, commitments, outcomes, or submission status. No agent may "
        "authorize or perform grant submission."
    )

    researcher = Agent(
        role="Funding Evidence Research Director",
        goal=(
            "Extract decision-relevant source facts, eligibility language, geography, deadlines, award data, "
            "requirements, evidence, and unknowns without inventing missing information."
        ),
        backstory=(
            "You are a doctoral-level nonprofit funding researcher who preserves provenance and separates "
            "verified facts from planning context. " + integrity_rule
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )

    eligibility = Agent(
        role="Eligibility and Compliance Counsel",
        goal=(
            "Determine hard applicant eligibility, tax-status restrictions, registrations, match obligations, "
            "required certifications, prohibited assumptions, and every unresolved eligibility gate."
        ),
        backstory=(
            "You are a federal grants compliance specialist. Mission fit never substitutes for eligibility, "
            "and uncertainty is always surfaced as a blocker or human-confirmation item. " + integrity_rule
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )

    strategist = Agent(
        role="Grant Strategy and Program Architecture Director",
        goal=(
            "Translate verified evidence and compliance constraints into a funder-specific pursuit strategy, "
            "program architecture, outcome logic, and persuasive narrative plan."
        ),
        backstory=(
            "You combine nonprofit strategy, housing, homelessness, reentry, workforce, community development, "
            "public-benefit economics, and reviewer psychology without overstating evidence. " + integrity_rule
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )

    writer = Agent(
        role="Senior Persuasive Grant Writer",
        goal=(
            "Produce precise, persuasive, funder-specific narrative that answers the exact question, uses only "
            "supported factual claims, and clearly labels prospective plans and unresolved information."
        ),
        backstory=(
            "You write at doctoral professional quality with strong ethos, pathos, logos, urgency, cost-benefit "
            "framing, and human dignity while refusing fabricated facts. " + integrity_rule
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )

    red_team = Agent(
        role="Independent Red-Team Grant Reviewer",
        goal=(
            "Adversarially challenge the draft for unsupported claims, weak logic, reviewer objections, missed "
            "requirements, overstatement, internal inconsistency, and avoidable scoring losses."
        ),
        backstory=(
            "You review as a skeptical funding panelist. Persuasion cannot cure missing evidence or compliance. "
            + integrity_rule
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )

    readiness = Agent(
        role="Submission Readiness Officer",
        goal=(
            "Issue a final staging verdict that distinguishes READY_FOR_HUMAN_REVIEW from REMEDIATION_REQUIRED "
            "and lists every human-only or unresolved item."
        ),
        backstory=(
            "You are the last AI gate before human review. You cannot approve submission, sign, certify, make a "
            "financial commitment, or convert an unresolved fact into a verified one. " + integrity_rule
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=6,
    )

    research_task = Task(
        description=(
            "Analyze this funding/application dossier. Produce an evidence brief covering official source facts, "
            "eligibility language, geography, deadline, award, priorities, required attachments/certifications, "
            "known facts, unknowns, source gaps, and explicit human-confirmation items. Dossier:\n{dossier}"
        ),
        expected_output="Evidence brief separating verified facts, planning context, unknowns, and source gaps.",
        agent=researcher,
    )

    eligibility_task = Task(
        description=(
            "Audit the evidence brief for hard eligibility and compliance. Identify applicant-type requirements, "
            "tax-status rules, registrations, match/cost share, required forms, certifications, deadline risks, "
            "prohibited assumptions, and hard blockers. Do not infer eligibility from mission alignment."
        ),
        expected_output="Eligibility/compliance memorandum with CONFIRMED, CONDITIONAL, UNKNOWN, and BLOCKED gates.",
        agent=eligibility,
        context=[research_task],
    )

    strategy_task = Task(
        description=(
            "Using the evidence and eligibility memorandum, produce the strongest lawful pursuit strategy, program "
            "positioning, reviewer-value proposition, measurable outcome logic, risks, and narrative outline."
        ),
        expected_output="Decision-ready strategy memo and narrative outline grounded in the prior two tasks.",
        agent=strategist,
        context=[research_task, eligibility_task],
    )

    writing_task = Task(
        description=(
            "Draft the response to this funder question: {question}. Stay within {max_words} words when a positive "
            "limit is supplied. Use only the evidence, eligibility memorandum, and strategy. Do not invent facts."
        ),
        expected_output="Evidence-grounded, funder-specific draft narrative.",
        agent=writer,
        context=[research_task, eligibility_task, strategy_task],
    )

    red_team_task = Task(
        description=(
            "Red-team the draft against the evidence, eligibility memo, strategy, and exact question. Identify "
            "unsupported claims, compliance gaps, omissions, contradictions, weak persuasion, and scoring risks."
        ),
        expected_output="Adversarial review with severity-ranked findings and exact revision requirements.",
        agent=red_team,
        context=[research_task, eligibility_task, strategy_task, writing_task],
    )

    readiness_task = Task(
        description=(
            "Issue the final AI staging decision after reviewing all prior work. First line must be exactly "
            "READINESS=READY_FOR_HUMAN_REVIEW or READINESS=REMEDIATION_REQUIRED. Then list unresolved facts, "
            "eligibility blockers, required revisions, human-only decisions, signatures/certifications, and the "
            "recommended next action. Never return SUBMITTED or APPROVED_FOR_SUBMISSION."
        ),
        expected_output="Deterministic-format staging verdict plus actionable human-review/remediation checklist.",
        agent=readiness,
        context=[research_task, eligibility_task, strategy_task, writing_task, red_team_task],
    )

    return runtime, Crew(
        agents=[researcher, eligibility, strategist, writer, red_team, readiness],
        tasks=[research_task, eligibility_task, strategy_task, writing_task, red_team_task, readiness_task],
        process=Process.sequential,
        verbose=False,
    )


def _readiness_status(output: str) -> str:
    first_line = output.strip().splitlines()[0].strip().upper() if output.strip() else ""
    if first_line == "READINESS=READY_FOR_HUMAN_REVIEW":
        return "READY_FOR_HUMAN_REVIEW"
    return "REMEDIATION_REQUIRED"


def _stage_result(
    *,
    runtime: CrewRuntime,
    dossier: str,
    question: str,
    max_words: int | None,
    output: str,
    staging_dir: Path = DEFAULT_STAGING_DIR,
    status: str | None = None,
    orchestration: str = ORCHESTRATION_MODE,
) -> tuple[str, str]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone()
    dossier_hash = hashlib.sha256(dossier.encode("utf-8")).hexdigest()
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    final_status = status or _readiness_status(output)
    record = {
        "created_at": timestamp.isoformat(),
        "provider": runtime.provider,
        "model": runtime.model,
        "orchestration": orchestration,
        "agent_count": AGENT_COUNT,
        "question": question,
        "max_words": max_words,
        "dossier_sha256": dossier_hash,
        "output": output,
        "output_sha256": output_hash,
        "status": final_status,
        "human_review_required": True,
        "external_side_effects_performed": False,
        "submission_performed": False,
        "safe_to_submit": False,
    }
    destination = staging_dir / (
        "crew_run_" + timestamp.strftime("%Y%m%d_%H%M%S_%f") + ".json"
    )
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(destination)
    destination.chmod(0o600)
    receipt_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
    return str(destination), receipt_hash


def run_grant_crew_raw(
    *,
    dossier: str,
    question: str,
    max_words: int | None = None,
    model: str | None = None,
) -> tuple[CrewRuntime, str]:
    if not dossier.strip():
        raise ValueError("dossier cannot be empty")
    if not question.strip():
        raise ValueError("question cannot be empty")
    if max_words is not None and max_words <= 0:
        raise ValueError("max_words must be positive when supplied")

    runtime, crew = build_grant_crew(model=model)
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
        raise RuntimeError("CrewAI returned empty output")
    return runtime, output


def kickoff_grant_crew(
    *,
    dossier: str,
    question: str,
    max_words: int | None = None,
    model: str | None = None,
) -> CrewRunResult:
    runtime, output = run_grant_crew_raw(
        dossier=dossier,
        question=question,
        max_words=max_words,
        model=model,
    )
    status = _readiness_status(output)
    artifact_path, artifact_sha256 = _stage_result(
        runtime=runtime,
        dossier=dossier,
        question=question,
        max_words=max_words,
        output=output,
        status=status,
        orchestration="crewai-crew-direct->deterministic-staging",
    )
    return CrewRunResult(
        output=output,
        provider=runtime.provider,
        model=runtime.model or "unknown",
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        status=status,
        orchestration="crewai-crew-direct->deterministic-staging",
        safe_to_submit=False,
    )
