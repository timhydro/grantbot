from __future__ import annotations

from typing import Any

from grantbot.claims.checker import check_claims
from grantbot.evidence.repository import list_requirements
from grantbot.knowledge.canonical import migrate_legacy_facts
from grantbot.learning.review_learning import (
    approved_examples,
    infer_funder_archetype,
    learning_profile,
)
from grantbot.master.database import record_feedback, save_revision
from grantbot.retrieval.hybrid import rank_facts
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

TASK_REQUIREMENT_CATEGORIES = {
    "BUDGET_FINANCE": {"BUDGET", "MATCH", "SUBMISSION"},
    "OUTCOMES_EVALUATION": {"REPORTING", "SCORING", "COMPLIANCE"},
    "ORGANIZATIONAL_CAPACITY": {"ELIGIBILITY", "ATTACHMENT", "COMPLIANCE"},
    "NEEDS_STATEMENT": {"SCORING", "GENERAL"},
    "SUSTAINABILITY": {"SCORING", "BUDGET", "MATCH"},
    "PROGRAM_NARRATIVE": {"ELIGIBILITY", "SCORING", "GENERAL"},
}


def _writer_fact(fact: dict[str, Any]) -> dict[str, Any] | None:
    fact_type = str(fact.get("fact_type", "")).upper()
    verification = str(fact.get("verification_state", "")).upper()
    if fact_type == "REASONABLE_PROJECTION":
        status = "DRAFT"
    elif verification == "APPROVED":
        status = "APPROVED"
    elif verification == "VERIFIED":
        status = "VERIFIED"
    else:
        return None
    return {
        "id": str(fact.get("fact_id", "")),
        "category": str(fact.get("category", "general")),
        "key": str(fact.get("fact_key", "")),
        "value": fact.get("value"),
        "status": status,
        "source": str(fact.get("source", "unknown")),
        "notes": str(fact.get("notes", "")),
        "fact_type": fact_type,
        "verification_state": verification,
        "retrieval_score": fact.get("retrieval_score"),
    }


def _relevant_facts(question: str, limit: int = 24) -> list[dict[str, Any]]:
    migrate_legacy_facts()
    ranked = rank_facts(question, limit=max(limit * 2, 20), include_unverified=True)
    selected: list[dict[str, Any]] = []
    for fact in ranked:
        converted = _writer_fact(fact)
        if converted is None:
            continue
        selected.append(converted)
        if len(selected) >= limit:
            break
    return selected


def _authoritative_requirements(
    opportunity_id: str,
    task_category: str,
    *,
    limit: int = 30,
) -> list[str]:
    try:
        records = list_requirements(
            opportunity_id=opportunity_id,
            authoritative_only=True,
        )
    except (ValueError, FileNotFoundError):
        return []
    categories = TASK_REQUIREMENT_CATEGORIES.get(task_category, {"GENERAL"})
    selected: list[str] = []
    for item in records:
        if str(item.get("category", "GENERAL")) not in categories:
            continue
        text = " ".join(str(item.get("text", "")).split()).strip()
        if text and text not in selected:
            selected.append(text)
        if len(selected) >= limit:
            break
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
    priorities = list(
        dict.fromkeys(
            list(blueprint.get("priorities") or [])
            + list(task.get("strategy") or [])
        )
    )
    requirements = list(
        dict.fromkeys(
            _authoritative_requirements(
                str(workspace.get("opportunity_id", "")),
                str(task.get("category", "PROGRAM_NARRATIVE")),
            )
            + list(blueprint.get("submission_requirements") or [])
            + list(task.get("evidence_requirements") or [])
        )
    )

    section = CATEGORY_TO_SECTION.get(task["category"], "general")
    funder_archetype = infer_funder_archetype(workspace)
    examples = approved_examples(
        query=str(task["question"]),
        section_type=section,
        funder_archetype=funder_archetype,
        limit=3,
    )
    profile = learning_profile(
        section_type=section,
        funder_archetype=funder_archetype,
    )

    result = write_answer(
        question=task["question"],
        section=section,
        facts=facts,
        grant_title=workspace.get("title", ""),
        funder=workspace.get("funder", ""),
        priorities=priorities,
        requirements=requirements,
        max_words=max_words,
        approved_examples=examples,
        learning_profile=profile,
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
            "source": f"fact:{fact.get('id', 'unknown')}",
            "note": (
                f"{fact.get('fact_type', 'UNKNOWN')} / "
                f"{fact.get('verification_state', fact.get('status', 'UNKNOWN'))}"
            ),
        }
        for fact in facts
    ]
    if examples:
        provenance.append(
            {
                "source": "human-approved-style-library",
                "note": (
                    f"{len(examples)} human-approved reference example(s) used "
                    "for style/structure only; not factual evidence"
                ),
            }
        )
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
        "authoritative_requirements": requirements,
        "missing_information": result.missing_information,
        "provider": result.provider,
        "model": result.model,
        "learning": {
            "approved_example_count": len(examples),
            "funder_archetype": funder_archetype,
            "profile": profile,
            "policy": "Examples influence style and structure only; current facts remain the sole factual evidence source.",
        },
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
            provenance=[
                {
                    "source": f"human:{reviewer.strip()}",
                    "note": "Legacy V18 feedback; not automatically admitted to V21 learning examples",
                }
            ],
        )
    return record
