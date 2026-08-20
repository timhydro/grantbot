from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from typing import Any

from grantbot.writing.ollama_provider import OllamaConfig, OllamaProvider


@dataclass(frozen=True, slots=True)
class CrewAIStatus:
    installed: bool
    ollama_available: bool
    configured_model: str
    selected_model: str | None
    base_url: str
    mode: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def crewai_installed() -> bool:
    return importlib.util.find_spec("crewai") is not None


def crewai_status() -> CrewAIStatus:
    config = OllamaConfig()
    health = OllamaProvider(config).health()
    return CrewAIStatus(
        installed=crewai_installed(),
        ollama_available=bool(health.get("available")),
        configured_model=config.model,
        selected_model=health.get("selected_model"),
        base_url=config.base_url,
        mode="local-ollama-only",
        error=str(health.get("error")) if health.get("error") else None,
    )


def _load_crewai():
    if not crewai_installed():
        raise RuntimeError(
            "CrewAI is not installed. Install GrantBot with the optional agents extra: "
            "python -m pip install -e '.[agents]'"
        )
    from crewai import Agent, Crew, LLM, Process, Task

    return Agent, Crew, LLM, Process, Task


def build_local_grant_crew(*, model: str | None = None, base_url: str | None = None):
    """Build a sequential CrewAI grant-analysis crew backed only by local Ollama.

    This bridge intentionally provides no hosted-provider credentials. CrewAI is
    configured with its documented ``ollama/<model>`` provider prefix and the local
    Ollama base URL. GrantBot's deterministic eligibility, evidence, quality, and
    human-review gates remain authoritative outside the crew.
    """

    Agent, Crew, LLM, Process, Task = _load_crewai()
    config = OllamaConfig()
    selected_model = model or config.model
    selected_base_url = (base_url or config.base_url).rstrip("/")
    llm = LLM(
        model=f"ollama/{selected_model}",
        base_url=selected_base_url,
        temperature=0.2,
    )

    researcher = Agent(
        role="Funding Evidence Research Director",
        goal=(
            "Extract decision-relevant eligibility, geography, deadline, award, priority, "
            "evidence, and compliance facts without inventing missing information."
        ),
        backstory=(
            "You are a doctoral-level nonprofit funding researcher. You distinguish source facts, "
            "reasonable planning context, and unknowns, and you never convert uncertainty into fact."
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
    strategist = Agent(
        role="Grant Strategy and Eligibility Director",
        goal=(
            "Determine mission fit, eligibility risk, pursuit priority, positioning, and the "
            "specific information that requires human confirmation."
        ),
        backstory=(
            "You combine nonprofit strategy, public funding compliance, housing, reentry, workforce, "
            "and community-development expertise with disciplined evidence standards."
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
    writer = Agent(
        role="Senior Persuasive Grant Writer",
        goal=(
            "Produce a precise, persuasive, funder-specific narrative using only supplied evidence "
            "and clearly prospective planning context."
        ),
        backstory=(
            "You write at doctoral professional quality while refusing fabricated statistics, budgets, "
            "partnerships, results, credentials, dates, counts, or commitments."
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
    reviewer = Agent(
        role="Independent Grant Quality and Compliance Reviewer",
        goal=(
            "Stress-test the proposed narrative for unsupported claims, missed requirements, weak logic, "
            "off-question content, compliance risk, and human-only decisions."
        ),
        backstory=(
            "You are an adversarial final reviewer. A polished narrative does not pass unless it is also "
            "truthful, relevant, traceable, and safe for human review."
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )

    research_task = Task(
        description=(
            "Analyze this funding/application dossier. Produce a concise evidence brief with eligibility, "
            "geography, deadline, award, priorities, required attachments/certifications, source-backed facts, "
            "unknowns, and explicit human-confirmation items. Dossier:\n{dossier}"
        ),
        expected_output="Structured evidence brief with verified facts, unknowns, and blockers.",
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
            "positive limit is supplied. Use the evidence brief and strategy memo only; do not invent facts."
        ),
        expected_output="Submission-quality draft narrative only.",
        agent=writer,
        context=[research_task, strategy_task],
    )
    review_task = Task(
        description=(
            "Review the draft against the evidence and strategy. Return PASS or REVISION_REQUIRED followed by "
            "specific unsupported claims, missing requirements, relevance problems, and human-only checks."
        ),
        expected_output="Quality/compliance verdict with actionable findings.",
        agent=reviewer,
        context=[research_task, strategy_task, writing_task],
    )

    return Crew(
        agents=[researcher, strategist, writer, reviewer],
        tasks=[research_task, strategy_task, writing_task, review_task],
        process=Process.sequential,
        verbose=False,
    )


def kickoff_local_grant_crew(
    *,
    dossier: str,
    question: str,
    max_words: int | None = None,
    model: str | None = None,
) -> str:
    if not dossier.strip():
        raise ValueError("dossier cannot be empty")
    if not question.strip():
        raise ValueError("question cannot be empty")
    crew = build_local_grant_crew(model=model)
    result = crew.kickoff(
        inputs={
            "dossier": dossier,
            "question": question,
            "max_words": max_words if max_words is not None else 0,
        }
    )
    raw = getattr(result, "raw", None)
    return str(raw if raw is not None else result).strip()
