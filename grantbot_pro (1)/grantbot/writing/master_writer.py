from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from grantbot.writing.ollama_provider import OllamaProvider
from grantbot.writing.quality_gate import evaluate_draft


TRUSTED = {"VERIFIED", "APPROVED"}
PLANNING = {"DRAFT"}

SECTION_STRATEGIES = {
    "executive_summary": "Lead with mission fit, problem, intervention, credibility, and investment case.",
    "statement_of_need": "Define the problem precisely using only supplied evidence.",
    "program_design": "Explain who does what, for whom, how, where, and in what sequence.",
    "goals_objectives": "Use measurable language only where targets are supplied.",
    "outcomes_evaluation": "Separate outputs, outcomes, and evaluation; never convert proposed outcomes into demonstrated results.",
    "organizational_capacity": "Use only verified leadership, experience, partnerships, systems, and governance.",
    "sustainability": "Describe realistic continuation mechanisms without inventing future funding.",
    "budget_narrative": "Connect verified costs to delivery; never invent line items or amounts.",
    "partnerships": "Describe only verified or approved partners and roles.",
    "general": "Answer the exact question directly using the strongest relevant facts.",
}


@dataclass(frozen=True, slots=True)
class WriterResult:
    status: str
    section: str
    question: str
    draft: str | None
    facts_used: list[dict[str, Any]]
    planning_context: list[dict[str, Any]]
    missing_information: list[dict[str, Any]]
    quality: dict[str, Any] | None
    provider: str
    model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(raw.get("id", "")).strip(),
        "category": str(raw.get("category", "general")).strip().lower(),
        "key": str(raw.get("key", "")).strip(),
        "value": raw.get("value", raw.get("answer")),
        "status": str(raw.get("status", "APPROVED")).strip().upper(),
        "source": str(raw.get("source", "unknown")).strip(),
        "notes": str(raw.get("notes", "")).strip(),
    }


def _partition(facts: list[dict[str, Any]]):
    trusted, planning, missing = [], [], []
    for raw in facts:
        fact = _normalize(raw)
        if fact["status"] in TRUSTED and fact["value"] not in (None, "", [], {}):
            trusted.append(fact)
        elif fact["status"] in PLANNING and fact["value"] not in (None, "", [], {}):
            planning.append(fact)
        elif fact["status"] == "MISSING":
            missing.append(fact)
    return trusted, planning, missing


def _block(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return "(none)"
    return "\n".join(
        f"- [{f['status']}] {f['category']}.{f['key']}: {f['value']} (source: {f['source']})"
        for f in facts
    )


def _system() -> str:
    return """
You are the senior grant strategist for BrokenGrowthMinistries with doctoral-level mastery of nonprofit grant strategy, housing/reentry programs, workforce development, evaluation, and persuasive professional writing.

Write the strongest truthful, funder-aligned response supported by the record.

Use ethos through credibility, pathos through dignified human stakes, and logos through implementation logic and responsible resource use. Frame funding as a high-value community investment when facts support that framing. Use precise, vivid language without exaggeration.

VERIFIED and APPROVED facts may be stated as facts.
DRAFT facts are planning context only and must remain prospective.
MISSING facts must never be guessed, estimated, rounded, or fabricated.
Never invent statistics, budgets, outcomes, partnerships, beneficiary counts, housing units, wages, dates, certifications, or success rates.
Return only the final grant narrative.
""".strip()


def write_answer(
    *,
    question: str,
    section: str,
    facts: list[dict[str, Any]],
    grant_title: str = "",
    funder: str = "",
    priorities: list[str] | None = None,
    requirements: list[str] | None = None,
    max_words: int | None = None,
    provider: OllamaProvider | None = None,
) -> WriterResult:
    if not question.strip():
        raise ValueError("question cannot be empty")

    section = section.strip().lower() or "general"
    if section not in SECTION_STRATEGIES:
        section = "general"

    trusted, planning, missing = _partition(facts)
    active = provider or OllamaProvider()

    if not trusted and not planning:
        return WriterResult(
            "MISSING_INFORMATION",
            section,
            question,
            None,
            [],
            [],
            missing,
            None,
            "ollama",
            active.config.model,
        )

    priorities = [p.strip() for p in (priorities or []) if p.strip()]
    requirements = [r.strip() for r in (requirements or []) if r.strip()]

    prompt = f"""
GRANT: {grant_title or "(not supplied)"}
FUNDER: {funder or "(not supplied)"}
SECTION: {section}
STRATEGY: {SECTION_STRATEGIES[section]}
QUESTION: {question}

FUNDER PRIORITIES:
{chr(10).join("- " + p for p in priorities) or "(none)"}

REQUIREMENTS:
{chr(10).join("- " + r for r in requirements) or "(none)"}

TRUSTED FACTS:
{_block(trusted)}

PLANNING CONTEXT:
{_block(planning)}

KNOWN MISSING:
{_block(missing)}

MAX WORDS: {max_words if max_words is not None else "not specified"}

Write only the final submission-quality narrative.
""".strip()

    draft = active.generate(prompt, system=_system(), temperature=0.3)
    quality = evaluate_draft(
        question=question,
        draft=draft,
        facts=trusted + planning,
        max_words=max_words,
        required_terms=priorities,
    )

    return WriterResult(
        "READY_FOR_HUMAN_REVIEW" if quality.passed else "REVISION_REQUIRED",
        section,
        question,
        draft,
        trusted,
        planning,
        missing,
        quality.to_dict(),
        "ollama",
        active.config.model,
    )
