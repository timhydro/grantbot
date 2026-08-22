from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from grantbot.writing.ollama_provider import OllamaConfig, OllamaProvider


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STAGING_DIR = PROJECT_ROOT / "data" / "crewai_staging"


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
    staging_enabled: bool
    external_side_effects_enabled: bool
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
    safe_to_submit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def crewai_installed() -> bool:
    return importlib.util.find_spec("crewai") is not None


def _select_runtime(
    *,
    environment: Mapping[str, str] | None = None,
    local_health: Mapping[str, Any] | None = None,
    model_override: str | None = None,
    base_url_override: str | None = None,
) -> CrewRuntime:
    env = dict(environment or os.environ)
    explicit_model = (model_override or env.get("GRANTBOT_CREWAI_MODEL", "")).strip()

    if explicit_model:
        if explicit_model.startswith("ollama/"):
            config = OllamaConfig()
            return CrewRuntime(
                available=True,
                provider="ollama",
                model=explicit_model,
                base_url=(base_url_override or env.get("GRANTBOT_CREWAI_BASE_URL") or config.base_url).rstrip("/"),
                mode="explicit-model",
            )

        provider = explicit_model.split("/", 1)[0].strip().lower()
        key_requirements = {
            "groq": "GROQ_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "cerebras": "CEREBRAS_API_KEY",
            "xai": "XAI_API_KEY",
        }
        required_key = key_requirements.get(provider)

        if required_key and not env.get(required_key, "").strip():
            return CrewRuntime(
                available=False,
                provider=provider,
                model=explicit_model,
                base_url=base_url_override or env.get("GRANTBOT_CREWAI_BASE_URL") or None,
                mode="explicit-model",
                reason=f"{required_key} is not loaded",
            )

        return CrewRuntime(
            available=True,
            provider=provider or "custom",
            model=explicit_model,
            base_url=base_url_override or env.get("GRANTBOT_CREWAI_BASE_URL") or None,
            mode="explicit-model",
        )

    # The automatic route is deliberately cost-protected. OpenRouter's free router
    # is preferred when configured. Metered providers require an explicit opt-in.
    if env.get("OPENROUTER_API_KEY", "").strip():
        return CrewRuntime(
            available=True,
            provider="openrouter",
            model="openrouter/openrouter/free",
            base_url=None,
            mode="automatic-free-cloud",
        )

    health = dict(local_health or {})
    if health.get("available") and health.get("model_installed"):
        config = OllamaConfig()
        selected = str(health.get("selected_model") or config.model).strip()
        return CrewRuntime(
            available=True,
            provider="ollama",
            model=f"ollama/{selected}",
            base_url=(base_url_override or config.base_url).rstrip("/"),
            mode="automatic-local",
        )

    if _truthy(env.get("GRANTBOT_ALLOW_METERED_AI")):
        if env.get("GROQ_API_KEY", "").strip():
            return CrewRuntime(
                available=True,
                provider="groq",
                model="groq/openai/gpt-oss-120b",
                base_url=None,
                mode="automatic-metered-cloud",
            )

        if env.get("GEMINI_API_KEY", "").strip():
            return CrewRuntime(
                available=True,
                provider="gemini",
                model="gemini/gemini-2.5-flash",
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
            "start an installed Ollama model, set GRANTBOT_CREWAI_MODEL explicitly, "
            "or opt in to metered AI with GRANTBOT_ALLOW_METERED_AI=1."
        ),
    )


def resolve_runtime(
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> CrewRuntime:
    config = OllamaConfig()
    health = OllamaProvider(config).health()
    return _select_runtime(
        environment=os.environ,
        local_health=health,
        model_override=model,
        base_url_override=base_url,
    )


def crewai_status() -> CrewAIStatus:
    installed = crewai_installed()
    runtime = resolve_runtime()
    return CrewAIStatus(
        installed=installed,
        available=bool(installed and runtime.available),
        provider=runtime.provider,
        model=runtime.model,
        base_url=runtime.base_url,
        mode=runtime.mode,
        staging_enabled=True,
        # Deliberately false: this runtime can write only local staging artifacts.
        # It cannot submit a grant, send email, edit Base44/Replit, or mutate GitHub.
        external_side_effects_enabled=False,
        safe_to_submit=False,
        error=None if (installed and runtime.available) else (
            runtime.reason if installed else "CrewAI is not installed"
        ),
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
    kwargs: dict[str, Any] = {
        "model": runtime.model,
        "temperature": 0.15,
    }
    if runtime.base_url:
        kwargs["base_url"] = runtime.base_url
    return LLM(**kwargs)


def build_grant_crew(
    *,
    model: str | None = None,
    base_url: str | None = None,
):
    Agent, Crew, _, Process, Task = _load_crewai()
    runtime = resolve_runtime(model=model, base_url=base_url)
    if not runtime.available or not runtime.model:
        raise RuntimeError(runtime.reason or "No CrewAI runtime is available")

    llm = _build_llm(runtime)

    integrity_rule = (
        "Never claim that an external action occurred unless the deterministic GrantBot runtime "
        "records a receipt for that action. Unknown and pending facts remain unknown or pending. "
        "No agent may authorize or perform grant submission."
    )

    researcher = Agent(
        role="Funding Evidence Research Director",
        goal=(
            "Extract decision-relevant eligibility, geography, deadline, award, priority, evidence, "
            "and compliance facts without inventing missing information."
        ),
        backstory=(
            "You are a doctoral-level nonprofit funding researcher. You distinguish source facts, "
            "planning context, and unknowns. " + integrity_rule
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=8,
    )

    strategist = Agent(
        role="Grant Strategy and Eligibility Director",
        goal=(
            "Determine mission fit, eligibility risk, pursuit priority, positioning, and every item "
            "requiring human confirmation."
        ),
        backstory=(
            "You combine nonprofit strategy, public funding compliance, housing, reentry, workforce, "
            "and community-development expertise. " + integrity_rule
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=8,
    )

    writer = Agent(
        role="Senior Persuasive Grant Writer",
        goal=(
            "Produce persuasive, funder-specific narrative using only supplied evidence and clearly "
            "labeled prospective planning context."
        ),
        backstory=(
            "You write at doctoral professional quality while refusing fabricated statistics, budgets, "
            "partnerships, results, credentials, dates, counts, approvals, or commitments. " + integrity_rule
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=8,
    )

    reviewer = Agent(
        role="Independent Grant Quality and Compliance Reviewer",
        goal=(
            "Stress-test the draft for unsupported claims, missed requirements, weak logic, off-question "
            "content, compliance risk, and human-only decisions."
        ),
        backstory=(
            "You are an adversarial final reviewer. A polished narrative does not pass unless it is truthful, "
            "relevant, traceable, and safe for human review. " + integrity_rule
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=8,
    )

    research_task = Task(
        description=(
            "Analyze this funding/application dossier. Produce a concise evidence brief with eligibility, "
            "geography, deadline, award, priorities, required attachments/certifications, source-backed facts, "
            "unknowns, and explicit human-confirmation items. Dossier:\n{dossier}"
        ),
        expected_output="Structured evidence brief with sourced facts, unknowns, and blockers.",
        agent=researcher,
    )

    strategy_task = Task(
        description=(
            "Using the evidence brief, produce a pursuit recommendation, positioning strategy, strengths, "
            "weaknesses, hard blockers, human-only decisions, and a narrative outline."
        ),
        expected_output="Decision-ready strategy memo and narrative outline.",
        agent=strategist,
        context=[research_task],
    )

    writing_task = Task(
        description=(
            "Draft the response to this funder question: {question}. Stay within {max_words} words when a "
            "positive limit is supplied. Use the evidence brief and strategy memo only. Do not invent facts."
        ),
        expected_output="Evidence-grounded draft narrative.",
        agent=writer,
        context=[research_task, strategy_task],
    )

    review_task = Task(
        description=(
            "Review the draft against the evidence and strategy. Return PASS_FOR_STAGING or REVISION_REQUIRED, "
            "then list unsupported claims, missing requirements, relevance problems, and human-only checks. "
            "Never return SUBMITTED or APPROVED_FOR_SUBMISSION."
        ),
        expected_output="Quality/compliance verdict with actionable findings.",
        agent=reviewer,
        context=[research_task, strategy_task, writing_task],
    )

    return runtime, Crew(
        agents=[researcher, strategist, writer, reviewer],
        tasks=[research_task, strategy_task, writing_task, review_task],
        process=Process.sequential,
        verbose=False,
    )


def _stage_result(
    *,
    runtime: CrewRuntime,
    dossier: str,
    question: str,
    max_words: int | None,
    output: str,
    staging_dir: Path = DEFAULT_STAGING_DIR,
) -> tuple[str, str]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone()
    dossier_hash = hashlib.sha256(dossier.encode("utf-8")).hexdigest()
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    record = {
        "created_at": timestamp.isoformat(),
        "provider": runtime.provider,
        "model": runtime.model,
        "question": question,
        "max_words": max_words,
        "dossier_sha256": dossier_hash,
        "output": output,
        "output_sha256": output_hash,
        "status": "READY_FOR_HUMAN_REVIEW",
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


def kickoff_grant_crew(
    *,
    dossier: str,
    question: str,
    max_words: int | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> CrewRunResult:
    if not dossier.strip():
        raise ValueError("dossier cannot be empty")
    if not question.strip():
        raise ValueError("question cannot be empty")

    runtime, crew = build_grant_crew(model=model, base_url=base_url)
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

    artifact_path, artifact_sha256 = _stage_result(
        runtime=runtime,
        dossier=dossier,
        question=question,
        max_words=max_words,
        output=output,
    )

    return CrewRunResult(
        output=output,
        provider=runtime.provider,
        model=runtime.model or "unknown",
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        safe_to_submit=False,
    )
