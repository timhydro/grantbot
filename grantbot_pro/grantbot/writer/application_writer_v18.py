from __future__ import annotations

from typing import Any

from grantbot.claims.checker import check_claims
from grantbot.knowledge.repository import working_facts
from grantbot.master.database import record_feedback, save_revision
from grantbot.review.staging_v17 import get_workspace, save_draft
from grantbot.writing.master_writer import write_answer


CATEGORY_TO_SECTION = {
    "BUDGET_FINANCE": "budget_narrative",
    "OUTCOMES_EVALUATION": "outcomes_evaluation",
    "ORGANIZATIONAL_CAPACITY": "organizational_capacity",
    "NEEDS_STATEMENT": "statement_of_need",
    "SUSTAINABILITY": "sustainability",
    "PROGRAM_NARRATIVE": "program_design",
}


def _fact_text(fact: dict[str, Any]) -> str:
    return " ".join(
        str(fact.get(key, ""))
        for key in ("category", "fact_key", "key", "value", "answer", "notes")
    ).lower()


def _relevant_facts(question: str, limit: int = 24) -> list[dict[str, Any]]:
    terms = {term.lower() for term in question.split() if len(term) >= 4}
    facts = working_facts()
    ranked = []
    for fact in facts:
        text = _fact_text(fact)
        overlap = sum(1 for term in terms if term in text)
        trust = {"APPROVED": 3, "VERIFIED": 2, "DRAFT": 1}.get(
            str(fact.get("status", "")).upper(), 0
        )
        ranked.append((overlap * 10 + trust, fact))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    selected = [fact for score, fact in ranked if score > 0][:limit]
    if not selected:
        selected = [fact for _, fact in ranked[: min(limit, 8)]]
    return selected


def draft_task(
    workspace_id: str,
    task_id: str,
    *,
    max_words: int | None = None,
) -> dict[str, Any]:
    workspace = get_workspace(workspace_id)
    task = next(
        (item for item in workspace["writer_tasks"] if item["task_id"] == task_id),
        None,
    )
    if task is None:
        raise FileNotFoundError(f"Writer task not found: {task_id}")

    facts = _relevant_facts(task["question"])
    analysis = workspace.get("analysis") or {}
    blueprint = analysis.get("blueprint") or {}
    priorities = list(dict.fromkeys(
        list(blueprint.get("priorities") or []) + list(task.get("strategy") or [])
    ))
    requirements = list(dict.fromkeys(
        list(blueprint.get("submission_requirements") or [])
        + list(task.get("evidence_requirements") or [])
    ))

    result = write_answer(
        question=task["question"],
        section=CATEGORY_TO_SECTION.get(task["category"], "general"),
        facts=facts,
        grant_title=workspace.get("title", ""),
        funder=workspace.get("funder", ""),
        priorities=priorities,
        requirements=requirements,
        max_words=max_words,
    )
    if not result.draft:
        return {
            "status": result.status,
            "workspace_id": workspace_id,
            "task_id": task_id,
            "missing_information": result.missing_information,
        }

    claims = check_claims(result.draft, facts)
    quality = result.quality or {}
    ready = bool(quality.get("passed")) and bool(claims.get("safe"))
    status = "READY_FOR_REVIEW" if ready else "DRAFT"
    revision = save_revision(
        workspace_id=workspace_id,
        task_id=task_id,
        content=result.draft,
        status=status,
        facts=facts,
        quality=quality,
        claims=claims,
        provider=result.provider,
        model=result.model,
    )
    provenance = [
        {
            "source": f"fact:{fact.get('id', fact.get('fact_key', fact.get('key', 'unknown')))}",
            "note": f"{fact.get('status', 'UNKNOWN')} organizational knowledge",
        }
        for fact in facts
    ]
    save_draft(
        workspace_id,
        task_id,
        response=result.draft,
        status=status,
        provenance=provenance,
    )
    return {
        "status": status,
        "workspace_id": workspace_id,
        "task_id": task_id,
        "revision": revision,
        "draft": result.draft,
        "quality": quality,
        "claims": claims,
        "facts_used": facts,
        "missing_information": result.missing_information,
        "provider": result.provider,
        "model": result.model,
    }


def submit_feedback(
    *,
    workspace_id: str,
    task_id: str,
    revision_id: str | None,
    before_text: str,
    after_text: str,
    accepted: bool,
    edit_tags: list[str],
    reviewer: str,
    reviewer_score: float | None = None,
    outcome: str = "",
    award_amount: float | None = None,
    section_type: str = "general",
    funder_archetype: str = "general",
) -> dict[str, Any]:
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    if reviewer_score is not None and not 0 <= reviewer_score <= 100:
        raise ValueError("reviewer_score must be between 0 and 100")
    if award_amount is not None and award_amount < 0:
        raise ValueError("award_amount cannot be negative")
    record = record_feedback(
        workspace_id=workspace_id,
        task_id=task_id,
        revision_id=revision_id,
        before_text=before_text,
        after_text=after_text,
        accepted=accepted,
        edit_tags=edit_tags,
        reviewer=reviewer.strip(),
        reviewer_score=reviewer_score,
        outcome=outcome.strip(),
        award_amount=award_amount,
        section_type=section_type.strip().lower() or "general",
        funder_archetype=funder_archetype.strip().lower() or "general",
    )
    if accepted and after_text.strip():
        save_draft(
            workspace_id,
            task_id,
            response=after_text.strip(),
            status="READY_FOR_REVIEW",
            provenance=[{"source": f"human:{reviewer.strip()}", "note": "Human-reviewed V18 revision"}],
        )
    return record
