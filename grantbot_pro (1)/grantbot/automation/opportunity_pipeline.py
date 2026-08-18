from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from grantbot.nofo.analyzer import analyze_nofo
from grantbot.writing.master_writer import write_answer
from grantbot.writing.ollama_provider import OllamaProvider


@dataclass(frozen=True, slots=True)
class Opportunity:
    id: str
    title: str
    funder: str = ""
    description: str = ""
    eligibility: str = ""
    deadline: str | None = None
    amount: float | None = None
    source_url: str = ""
    nofo_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _load_facts() -> list[dict[str, Any]]:
    try:
        from grantbot.knowledge.fact_registry import FactRegistry
    except ImportError:
        return []

    registry = FactRegistry()

    raw_facts = None

    if hasattr(registry, "all") and callable(registry.all):
        raw_facts = registry.all()
    elif hasattr(registry, "get_all") and callable(registry.get_all):
        raw_facts = registry.get_all()
    elif hasattr(registry, "get_all_facts") and callable(registry.get_all_facts):
        raw_facts = registry.get_all_facts()
    elif hasattr(registry, "_facts"):
        raw_facts = registry._facts

    if raw_facts is None:
        return []

    if isinstance(raw_facts, dict):
        if isinstance(raw_facts.get("facts"), list):
            raw_facts = raw_facts["facts"]
        else:
            raw_facts = [
                {
                    "id": str(key),
                    "category": "general",
                    "key": str(key),
                    "value": value,
                    "status": "APPROVED",
                    "source": "legacy_fact_registry",
                }
                for key, value in raw_facts.items()
            ]

    facts: list[dict[str, Any]] = []

    for fact in raw_facts:
        if hasattr(fact, "to_dict") and callable(fact.to_dict):
            item = fact.to_dict()
        elif isinstance(fact, dict):
            item = dict(fact)
        else:
            continue

        item.setdefault("id", str(item.get("key", "")))
        item.setdefault("category", "general")
        item.setdefault("key", item.get("id", ""))
        item.setdefault("status", "APPROVED")
        item.setdefault("source", "fact_registry")

        facts.append(item)

    return facts


def _relevant(question: str, facts: list[dict[str, Any]], limit: int = 12):
    words = {
        w
        for w in re_clean(question)
        if len(w) >= 4
    }
    scored = []
    for fact in facts:
        status = str(fact.get("status", "")).upper()
        if status not in {"VERIFIED", "APPROVED", "DRAFT"}:
            continue
        searchable = " ".join(
            (
                str(fact.get("category", "")),
                str(fact.get("key", "")),
                str(fact.get("value", "")),
            )
        ).lower()
        score = sum(1 for w in words if w in searchable)
        if score:
            scored.append((score, fact))
    scored.sort(key=lambda x: -x[0])
    return [fact for _, fact in scored[:limit]]


def re_clean(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return cleaned.split()


def analyze_opportunity(
    opportunity: Opportunity,
    *,
    generate_drafts: bool = False,
) -> dict[str, Any]:
    text = " ".join(
        (
            opportunity.title,
            opportunity.description,
            opportunity.eligibility,
            opportunity.nofo_text,
        )
    )

    nofo = analyze_nofo(
        text,
        title=opportunity.title,
        funder=opportunity.funder,
    )

    blockers = list(nofo.blockers)

    if opportunity.deadline:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y"):
            try:
                d = datetime.strptime(opportunity.deadline, fmt).date()
                if d < date.today():
                    blockers.append(f"deadline passed on {d.isoformat()}")
                break
            except ValueError:
                continue

    hard = nofo.hard_reject or any(b.startswith("deadline passed") for b in blockers)
    score = 0 if hard else nofo.fit_score

    if hard:
        priority = "REJECT"
    elif score >= 80:
        priority = "HIGH"
    elif score >= 60:
        priority = "MEDIUM"
    elif score >= 40:
        priority = "LOW"
    else:
        priority = "VERY_LOW"

    facts = _load_facts()
    missing = [
        f"{f.get('category', 'general')}.{f.get('key', '')}"
        for f in facts
        if str(f.get("status", "")).upper() == "MISSING"
    ]

    writer_packages = []

    if generate_drafts and not hard:
        provider = OllamaProvider()
        health = provider.health()
        if not health.get("available") or not health.get("model_installed"):
            raise RuntimeError(f"Ollama not ready: {health}")

        for question in nofo.application_questions:
            relevant = _relevant(question, facts)
            result = write_answer(
                question=question,
                section="general",
                facts=relevant,
                grant_title=opportunity.title,
                funder=opportunity.funder,
                priorities=nofo.priorities,
                requirements=nofo.requirements,
                provider=provider,
            )
            writer_packages.append(result.to_dict())

    readiness = 0 if hard else min(
        100,
        50
        + min(20, len(nofo.application_questions) * 3)
        + (20 if not missing else max(0, 20 - len(missing) * 2))
        + min(10, sum(1 for p in writer_packages if p.get("status") == "READY_FOR_HUMAN_REVIEW") * 2),
    )

    return {
        "id": opportunity.id,
        "title": opportunity.title,
        "funder": opportunity.funder,
        "score": score,
        "priority": priority,
        "hard_reject": hard,
        "blockers": blockers,
        "deadline": opportunity.deadline,
        "amount": opportunity.amount,
        "source_url": opportunity.source_url,
        "matched_domains": nofo.matched_domains,
        "nofo": nofo.to_dict(),
        "missing_information": missing,
        "readiness_score": readiness,
        "writer_packages": writer_packages,
    }


def rank_opportunities(
    opportunities: list[Opportunity],
    *,
    generate_drafts: bool = False,
) -> list[dict[str, Any]]:
    seen = set()
    unique = []

    for item in opportunities:
        key = item.id.strip().lower() or (
            item.title.strip().lower(),
            item.funder.strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    results = [
        analyze_opportunity(item, generate_drafts=generate_drafts)
        for item in unique
    ]

    return sorted(
        results,
        key=lambda x: (
            x["hard_reject"],
            -x["score"],
            -x["readiness_score"],
            x["title"].lower(),
        ),
    )
