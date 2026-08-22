from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from grantbot.agents.crewai_multimodel import resolve_role_runtime
from grantbot.agents.crewai_runtime import CrewRuntime, _build_llm, resolve_runtime


PANEL_ORDER = (
    "compliance",
    "program",
    "budget",
    "evidence",
    "writing",
)
PANEL_ENV_VARS = {
    "compliance": "GRANTBOT_PANEL_COMPLIANCE_MODEL",
    "program": "GRANTBOT_PANEL_PROGRAM_MODEL",
    "budget": "GRANTBOT_PANEL_BUDGET_MODEL",
    "evidence": "GRANTBOT_PANEL_EVIDENCE_MODEL",
    "writing": "GRANTBOT_PANEL_WRITING_MODEL",
}


@dataclass(frozen=True, slots=True)
class PanelResult:
    status: str
    reviews: dict[str, str]
    models: dict[str, dict[str, Any]]
    consolidated_findings: str
    human_review_required: bool = True
    reviewer_rewrite_allowed: bool = False
    submission_performed: bool = False
    safe_to_submit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _runtime_for_panel(role: str, environment: Mapping[str, str] | None = None) -> CrewRuntime:
    if role not in PANEL_ORDER:
        raise ValueError(f"Unknown adversarial panel role: {role}")
    env = dict(environment or os.environ)
    explicit = str(env.get(PANEL_ENV_VARS[role], "")).strip()
    if explicit:
        runtime = resolve_runtime(model=explicit)
        if runtime.available and runtime.model:
            return CrewRuntime(
                available=True,
                provider=runtime.provider,
                model=runtime.model,
                base_url=runtime.base_url,
                mode=f"panel:{role}:explicit:{runtime.mode}",
            )
        raise RuntimeError(runtime.reason or f"Configured model for panel role {role} is unavailable")

    mapping = {
        "compliance": "eligibility",
        "program": "strategy",
        "budget": "red_team",
        "evidence": "research",
        "writing": "red_team",
    }
    runtime = resolve_role_runtime(mapping[role], environment=env)
    if not runtime.available or not runtime.model:
        raise RuntimeError(runtime.reason or f"No model available for panel role {role}")
    return CrewRuntime(
        available=True,
        provider=runtime.provider,
        model=runtime.model,
        base_url=runtime.base_url,
        mode=f"panel:{role}:{runtime.mode}",
    )


def panel_status(environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = dict(environment or os.environ)
    roles: dict[str, dict[str, Any]] = {}
    available = True
    for role in PANEL_ORDER:
        try:
            runtime = _runtime_for_panel(role, env)
            roles[role] = {
                "available": True,
                "provider": runtime.provider,
                "model": runtime.model,
                "mode": runtime.mode,
                "reason": None,
            }
        except RuntimeError as exc:
            available = False
            roles[role] = {
                "available": False,
                "provider": "none",
                "model": None,
                "mode": f"panel:{role}:unavailable",
                "reason": str(exc),
            }
    return {
        "available": available,
        "roles": roles,
        "human_review_required": True,
        "reviewer_rewrite_allowed": False,
        "submission_performed": False,
        "safe_to_submit": False,
    }


def run_adversarial_panel(
    *,
    dossier: str,
    final_answer: str,
    budget_context: Mapping[str, Any] | None = None,
    environment: Mapping[str, str] | None = None,
) -> PanelResult:
    if not dossier.strip():
        raise ValueError("dossier cannot be empty")
    if not final_answer.strip():
        raise ValueError("final_answer cannot be empty")

    try:
        from crewai import Agent, Crew, Process, Task
    except ImportError as exc:
        raise RuntimeError(
            "CrewAI is not installed. Install GrantBot with: python -m pip install -e '.[agents]'"
        ) from exc

    env = dict(environment or os.environ)
    runtimes = {role: _runtime_for_panel(role, env) for role in PANEL_ORDER}
    llms = {role: _build_llm(runtime) for role, runtime in runtimes.items()}
    for role, temperature in {
        "compliance": 0.0,
        "program": 0.05,
        "budget": 0.0,
        "evidence": 0.0,
        "writing": 0.05,
    }.items():
        try:
            llms[role].temperature = temperature
        except Exception:
            pass

    immutable_rule = (
        "You are a reviewer, not an author. Do not rewrite, paraphrase, replace, or supply substitute applicant-facing prose. "
        "Return findings, severity, evidence, and exact revision instructions only. Never invent facts, requirements, financial data, "
        "reviewer comments, eligibility, approvals, signatures, certifications, or submission status."
    )

    agents = {
        "compliance": Agent(
            role="Adversarial Compliance Reviewer",
            goal="Find every eligibility, regulatory, certification, attachment, and submission-risk defect.",
            backstory="You review as a strict government grants compliance officer. " + immutable_rule,
            llm=llms["compliance"], verbose=False, allow_delegation=False, max_iter=5,
        ),
        "program": Agent(
            role="Adversarial Program Officer",
            goal="Find gaps between funder intent, program design, outputs, outcomes, implementation, and organizational capacity.",
            backstory="You review as a skeptical program officer deciding whether the intervention merits funding. " + immutable_rule,
            llm=llms["program"], verbose=False, allow_delegation=False, max_iter=5,
        ),
        "budget": Agent(
            role="Adversarial Budget Reviewer",
            goal="Find arithmetic, allowability, reasonableness, allocation, match, and narrative-to-budget inconsistencies.",
            backstory="You review as a grants management and cost-principles specialist. " + immutable_rule,
            llm=llms["budget"], verbose=False, allow_delegation=False, max_iter=5,
        ),
        "evidence": Agent(
            role="Adversarial Evidence Reviewer",
            goal="Find unsupported claims, weak provenance, overclaiming, stale evidence, and missing proof.",
            backstory="You review as an evidence-methods specialist who requires source-grounded assertions. " + immutable_rule,
            llm=llms["evidence"], verbose=False, allow_delegation=False, max_iter=5,
        ),
        "writing": Agent(
            role="Adversarial Scoring-Panel Writing Reviewer",
            goal="Find unclear, generic, repetitive, indirect, unscorable, or weakly persuasive language without rewriting it.",
            backstory="You review as a competitive grant panelist scoring clarity, specificity, responsiveness, and persuasion. " + immutable_rule,
            llm=llms["writing"], verbose=False, allow_delegation=False, max_iter=5,
        ),
    }

    shared = (
        "DOSSIER:\n{dossier}\n\nFINAL MASTER-WRITER ANSWER:\n{final_answer}\n\n"
        "BUDGET CONTEXT:\n{budget_context}\n\n"
        "Classify each finding as BLOCKER, MAJOR, MINOR, or INFO. For every non-INFO finding, cite the exact issue and state the correction required. "
        "Do not produce replacement prose."
    )
    tasks = [
        Task(description=f"Perform the {role} review.\n\n{shared}", expected_output=f"{role} review findings only.", agent=agents[role])
        for role in PANEL_ORDER
    ]

    crew = Crew(
        agents=[agents[role] for role in PANEL_ORDER],
        tasks=tasks,
        process=Process.sequential,
        verbose=False,
    )
    result = crew.kickoff(
        inputs={
            "dossier": dossier,
            "final_answer": final_answer,
            "budget_context": json.dumps(dict(budget_context or {}), ensure_ascii=False, sort_keys=True, default=str),
        }
    )
    outputs = getattr(result, "tasks_output", None)
    if not isinstance(outputs, (list, tuple)) or len(outputs) != len(PANEL_ORDER):
        raise RuntimeError("Adversarial panel did not return one output per reviewer")

    reviews: dict[str, str] = {}
    for index, role in enumerate(PANEL_ORDER):
        item = outputs[index]
        raw = getattr(item, "raw", None)
        text = str(raw if raw is not None else item).strip()
        if not text:
            raise RuntimeError(f"Adversarial panel returned empty review for {role}")
        reviews[role] = text

    blocker_terms = sum(review.upper().count("BLOCKER") for review in reviews.values())
    major_terms = sum(review.upper().count("MAJOR") for review in reviews.values())
    status = "REMEDIATION_REQUIRED" if blocker_terms or major_terms else "READY_FOR_HUMAN_REVIEW"
    consolidated = "\n\n".join(
        f"[{role.upper()}]\n{reviews[role]}" for role in PANEL_ORDER
    )
    return PanelResult(
        status=status,
        reviews=reviews,
        models={
            role: {
                "provider": runtimes[role].provider,
                "model": runtimes[role].model,
                "mode": runtimes[role].mode,
            }
            for role in PANEL_ORDER
        },
        consolidated_findings=consolidated,
    )
