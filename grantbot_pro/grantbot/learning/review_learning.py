from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from typing import Any

from grantbot.claims.checker import check_claims
from grantbot.core.database import connection, utc_now
from grantbot.master.database import (
    list_revisions,
    record_feedback,
    save_revision,
)
from grantbot.review.staging_v17 import get_workspace, save_draft


DIMENSION_WEIGHTS: dict[str, float] = {
    "funder_alignment": 0.15,
    "evidence_fidelity": 0.20,
    "requirement_compliance": 0.20,
    "clarity": 0.10,
    "persuasion": 0.10,
    "measurability": 0.10,
    "implementation_feasibility": 0.10,
    "financial_consistency": 0.05,
}

DECISIONS = {"APPROVE", "REVISE", "REJECT"}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")


def initialize_review_learning_schema() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS review_scorecards_v21 (
                review_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                source_revision_id TEXT NOT NULL,
                human_revision_id TEXT NOT NULL DEFAULT '',
                decision TEXT NOT NULL,
                overall_score REAL NOT NULL,
                dimensions_json TEXT NOT NULL,
                rationale TEXT NOT NULL,
                edit_tags_json TEXT NOT NULL,
                before_text TEXT NOT NULL,
                after_text TEXT NOT NULL,
                claims_json TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                section_type TEXT NOT NULL,
                funder_archetype TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT '',
                award_amount REAL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_review_scorecards_context_v21
                ON review_scorecards_v21(
                    section_type, funder_archetype, decision, created_at
                );

            CREATE INDEX IF NOT EXISTS idx_review_scorecards_workspace_v21
                ON review_scorecards_v21(workspace_id, task_id, created_at);

            CREATE TABLE IF NOT EXISTS learning_examples_v21 (
                example_id TEXT PRIMARY KEY,
                review_id TEXT NOT NULL UNIQUE,
                workspace_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                human_revision_id TEXT NOT NULL,
                question TEXT NOT NULL,
                section_type TEXT NOT NULL,
                funder_archetype TEXT NOT NULL,
                final_text TEXT NOT NULL,
                reviewer_score REAL NOT NULL,
                edit_tags_json TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT '',
                award_amount REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(review_id)
                    REFERENCES review_scorecards_v21(review_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_learning_examples_context_v21
                ON learning_examples_v21(
                    section_type, funder_archetype, reviewer_score DESC
                );
            """
        )


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_tag(value: Any) -> str:
    return re.sub(r"[^a-z0-9_ -]+", "", _clean(value).casefold()).replace(" ", "_")[:80]


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in TOKEN_RE.findall(text)}


def _similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _dimension_scores(dimensions: dict[str, Any]) -> tuple[dict[str, float], float]:
    missing = sorted(set(DIMENSION_WEIGHTS) - set(dimensions))
    unknown = sorted(set(dimensions) - set(DIMENSION_WEIGHTS))
    if missing:
        raise ValueError("Missing review dimension(s): " + ", ".join(missing))
    if unknown:
        raise ValueError("Unknown review dimension(s): " + ", ".join(unknown))

    clean: dict[str, float] = {}
    for name in DIMENSION_WEIGHTS:
        try:
            score = float(dimensions[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Review dimension {name} must be numeric") from exc
        if not 0 <= score <= 100:
            raise ValueError(f"Review dimension {name} must be between 0 and 100")
        clean[name] = round(score, 2)

    overall = round(
        sum(clean[name] * DIMENSION_WEIGHTS[name] for name in DIMENSION_WEIGHTS),
        2,
    )
    return clean, overall


def _revision(
    workspace_id: str,
    task_id: str,
    revision_id: str,
) -> dict[str, Any]:
    revisions = list_revisions(workspace_id, task_id)
    for item in revisions:
        if str(item.get("revision_id", "")) == revision_id:
            return item
    raise FileNotFoundError(f"Draft revision not found: {revision_id}")


def _task(workspace: dict[str, Any], task_id: str) -> dict[str, Any]:
    for item in workspace.get("writer_tasks", []):
        if str(item.get("task_id", "")) == task_id:
            return item
    raise FileNotFoundError(f"Writer task not found: {task_id}")


def infer_funder_archetype(workspace: dict[str, Any]) -> str:
    material = " ".join(
        [
            str(workspace.get("funder", "")),
            str(workspace.get("title", "")),
            str((workspace.get("analysis") or {}).get("blueprint", {}).get("agency", "")),
        ]
    ).casefold()
    if any(
        term in material
        for term in (
            "department",
            "agency",
            "county",
            "city of",
            "state of",
            "hud",
            "justice",
            "federal",
            "government",
        )
    ):
        return "government"
    if "foundation" in material or "trust" in material:
        return "foundation"
    if any(term in material for term in ("bank", "corporate", "company", "csr")):
        return "corporate"
    if any(term in material for term in ("church", "faith", "ministry")):
        return "faith"
    if any(term in material for term in ("invest", "capital", "venture", "angel")):
        return "investor"
    return "general"


def _insert_scorecard(
    *,
    review_id: str,
    workspace_id: str,
    task_id: str,
    source_revision_id: str,
    human_revision_id: str,
    decision: str,
    overall_score: float,
    dimensions: dict[str, float],
    rationale: str,
    edit_tags: list[str],
    before_text: str,
    after_text: str,
    claims: dict[str, Any],
    reviewer: str,
    section_type: str,
    funder_archetype: str,
    outcome: str,
    award_amount: float | None,
    created_at: str,
) -> None:
    initialize_review_learning_schema()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO review_scorecards_v21(
                review_id, workspace_id, task_id, source_revision_id,
                human_revision_id, decision, overall_score, dimensions_json,
                rationale, edit_tags_json, before_text, after_text, claims_json,
                reviewer, section_type, funder_archetype, outcome, award_amount,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                workspace_id,
                task_id,
                source_revision_id,
                human_revision_id,
                decision,
                overall_score,
                json.dumps(dimensions, ensure_ascii=False, sort_keys=True),
                rationale,
                json.dumps(edit_tags, ensure_ascii=False),
                before_text,
                after_text,
                json.dumps(claims, ensure_ascii=False, sort_keys=True),
                reviewer,
                section_type,
                funder_archetype,
                outcome,
                award_amount,
                created_at,
            ),
        )


def _insert_learning_example(
    *,
    review_id: str,
    workspace_id: str,
    task_id: str,
    human_revision_id: str,
    question: str,
    section_type: str,
    funder_archetype: str,
    final_text: str,
    reviewer_score: float,
    edit_tags: list[str],
    outcome: str,
    award_amount: float | None,
    created_at: str,
) -> None:
    initialize_review_learning_schema()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO learning_examples_v21(
                example_id, review_id, workspace_id, task_id,
                human_revision_id, question, section_type,
                funder_archetype, final_text, reviewer_score,
                edit_tags_json, outcome, award_amount, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                review_id,
                workspace_id,
                task_id,
                human_revision_id,
                question,
                section_type,
                funder_archetype,
                final_text,
                reviewer_score,
                json.dumps(edit_tags, ensure_ascii=False),
                outcome,
                award_amount,
                created_at,
            ),
        )


def submit_review(
    *,
    workspace_id: str,
    task_id: str,
    revision_id: str,
    decision: str,
    dimensions: dict[str, Any],
    rationale: str,
    edit_tags: list[str],
    reviewer: str,
    final_text: str = "",
    section_type: str = "",
    funder_archetype: str = "",
    outcome: str = "",
    award_amount: float | None = None,
) -> dict[str, Any]:
    decision = _clean(decision).upper()
    if decision not in DECISIONS:
        raise ValueError("decision must be APPROVE, REVISE, or REJECT")
    reviewer = _clean(reviewer)
    rationale = _clean(rationale)
    if not reviewer:
        raise ValueError("reviewer is required")
    if not rationale:
        raise ValueError("rationale is required")
    if award_amount is not None and award_amount < 0:
        raise ValueError("award_amount cannot be negative")

    clean_dimensions, overall_score = _dimension_scores(dimensions)
    workspace = get_workspace(workspace_id)
    task = _task(workspace, task_id)
    source = _revision(workspace_id, task_id, revision_id)
    before_text = str(source.get("content", "")).strip()
    if not before_text:
        raise ValueError("Source revision has no content")

    section = _clean(section_type).casefold() or str(task.get("category", "general")).casefold()
    archetype = _clean(funder_archetype).casefold() or infer_funder_archetype(workspace)
    tags = list(
        dict.fromkeys(
            tag
            for tag in (_normalize_tag(item) for item in edit_tags)
            if tag
        )
    )[:50]
    after_text = str(final_text or "").strip() or before_text
    facts = list(source.get("facts", []) or [])
    claims = check_claims(after_text, facts)

    if decision == "APPROVE":
        if overall_score < 80:
            raise ValueError("APPROVE requires an overall reviewer score of at least 80")
        weak = [name for name, score in clean_dimensions.items() if score < 65]
        if weak:
            raise ValueError(
                "APPROVE requires every review dimension to score at least 65: "
                + ", ".join(weak)
            )
        if not claims.get("safe"):
            raise ValueError(
                "APPROVE is blocked because the final text contains unsupported claims"
            )

    human_revision_id = ""
    revision_status = ""
    if decision in {"APPROVE", "REVISE"} and after_text:
        revision_status = (
            "APPROVED"
            if decision == "APPROVE"
            else ("READY_FOR_REVIEW" if claims.get("safe") else "DRAFT")
        )
        human_revision = save_revision(
            workspace_id=workspace_id,
            task_id=task_id,
            content=after_text,
            status=revision_status,
            facts=facts,
            quality={
                "passed": decision == "APPROVE",
                "human_review": True,
                "overall_score": overall_score,
                "dimensions": clean_dimensions,
                "rationale": rationale,
            },
            claims=claims,
            provider="human-review",
            model=reviewer,
        )
        human_revision_id = str(human_revision.get("revision_id", ""))
        save_draft(
            workspace_id,
            task_id,
            response=after_text,
            status=revision_status,
            provenance=[
                {
                    "source": f"human-review:{reviewer}",
                    "note": (
                        f"Adjudicated review {decision}; score {overall_score:.2f}; "
                        f"source revision {revision_id}"
                    ),
                }
            ],
        )

    created_at = utc_now()
    review_id = uuid.uuid4().hex
    _insert_scorecard(
        review_id=review_id,
        workspace_id=workspace_id,
        task_id=task_id,
        source_revision_id=revision_id,
        human_revision_id=human_revision_id,
        decision=decision,
        overall_score=overall_score,
        dimensions=clean_dimensions,
        rationale=rationale,
        edit_tags=tags,
        before_text=before_text,
        after_text=after_text,
        claims=claims,
        reviewer=reviewer,
        section_type=section,
        funder_archetype=archetype,
        outcome=_clean(outcome),
        award_amount=award_amount,
        created_at=created_at,
    )

    record_feedback(
        workspace_id=workspace_id,
        task_id=task_id,
        revision_id=revision_id,
        before_text=before_text,
        after_text=after_text,
        accepted=decision == "APPROVE",
        edit_tags=tags,
        reviewer=reviewer,
        reviewer_score=overall_score,
        outcome=_clean(outcome),
        award_amount=award_amount,
        section_type=section,
        funder_archetype=archetype,
    )

    if decision == "APPROVE":
        _insert_learning_example(
            review_id=review_id,
            workspace_id=workspace_id,
            task_id=task_id,
            human_revision_id=human_revision_id,
            question=str(task.get("question", "")),
            section_type=section,
            funder_archetype=archetype,
            final_text=after_text,
            reviewer_score=overall_score,
            edit_tags=tags,
            outcome=_clean(outcome),
            award_amount=award_amount,
            created_at=created_at,
        )

    return {
        "review_id": review_id,
        "workspace_id": workspace_id,
        "task_id": task_id,
        "source_revision_id": revision_id,
        "human_revision_id": human_revision_id,
        "decision": decision,
        "overall_score": overall_score,
        "dimensions": clean_dimensions,
        "rationale": rationale,
        "edit_tags": tags,
        "claims": claims,
        "section_type": section,
        "funder_archetype": archetype,
        "learning_example_created": decision == "APPROVE",
        "revision_status": revision_status,
        "created_at": created_at,
    }


def _decode_review(row: Any) -> dict[str, Any]:
    item = dict(row)
    for source, target, default in (
        ("dimensions_json", "dimensions", {}),
        ("edit_tags_json", "edit_tags", []),
        ("claims_json", "claims", {}),
    ):
        try:
            item[target] = json.loads(str(item.pop(source)))
        except json.JSONDecodeError:
            item[target] = default
    return item


def review_history(
    workspace_id: str,
    *,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    initialize_review_learning_schema()
    sql = "SELECT * FROM review_scorecards_v21 WHERE workspace_id=?"
    params: list[Any] = [workspace_id]
    if task_id:
        sql += " AND task_id=?"
        params.append(task_id)
    sql += " ORDER BY created_at DESC, review_id DESC"
    with connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_decode_review(row) for row in rows]


def approved_examples(
    *,
    query: str,
    section_type: str = "general",
    funder_archetype: str = "general",
    limit: int = 3,
) -> list[dict[str, Any]]:
    initialize_review_learning_schema()
    safe_limit = min(max(int(limit), 1), 10)
    section = _clean(section_type).casefold() or "general"
    archetype = _clean(funder_archetype).casefold() or "general"
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM learning_examples_v21
            ORDER BY reviewer_score DESC, created_at DESC
            LIMIT 250
            """
        ).fetchall()

    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        item = dict(row)
        similarity = _similarity(query, str(item.get("question", "")))
        section_bonus = 1.0 if str(item.get("section_type", "")) == section else 0.0
        funder_bonus = 1.0 if str(item.get("funder_archetype", "")) == archetype else 0.0
        reviewer_score = float(item.get("reviewer_score", 0) or 0) / 100.0
        rank = (
            similarity * 0.60
            + section_bonus * 0.20
            + funder_bonus * 0.10
            + reviewer_score * 0.10
        )
        try:
            tags = json.loads(str(item.pop("edit_tags_json")))
        except json.JSONDecodeError:
            tags = []
        item["edit_tags"] = tags
        item["retrieval_score"] = round(rank, 4)
        ranked.append((rank, item))

    ranked.sort(
        key=lambda pair: (
            pair[0],
            float(pair[1].get("reviewer_score", 0) or 0),
            str(pair[1].get("created_at", "")),
        ),
        reverse=True,
    )
    return [item for _, item in ranked[:safe_limit]]


def learning_profile(
    *,
    section_type: str | None = None,
    funder_archetype: str | None = None,
) -> dict[str, Any]:
    initialize_review_learning_schema()
    sql = "SELECT * FROM review_scorecards_v21 WHERE 1=1"
    params: list[Any] = []
    if section_type:
        sql += " AND section_type=?"
        params.append(_clean(section_type).casefold())
    if funder_archetype:
        sql += " AND funder_archetype=?"
        params.append(_clean(funder_archetype).casefold())
    with connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    reviews = [_decode_review(row) for row in rows]
    approved = [item for item in reviews if item.get("decision") == "APPROVE"]
    tags = Counter(
        tag
        for item in approved
        for tag in item.get("edit_tags", [])
    )
    scores = [float(item.get("overall_score", 0) or 0) for item in approved]
    compression_ratios: list[float] = []
    for item in approved:
        before_words = len(str(item.get("before_text", "")).split())
        after_words = len(str(item.get("after_text", "")).split())
        if before_words:
            compression_ratios.append(after_words / before_words)

    dimension_averages: dict[str, float | None] = {}
    for dimension in DIMENSION_WEIGHTS:
        values = [
            float(item["dimensions"][dimension])
            for item in approved
            if dimension in item.get("dimensions", {})
        ]
        dimension_averages[dimension] = (
            round(sum(values) / len(values), 2) if values else None
        )

    return {
        "review_count": len(reviews),
        "approved_count": len(approved),
        "approval_rate": round(len(approved) / len(reviews), 4) if reviews else 0.0,
        "average_approved_score": round(sum(scores) / len(scores), 2) if scores else None,
        "average_final_to_source_word_ratio": (
            round(sum(compression_ratios) / len(compression_ratios), 3)
            if compression_ratios
            else None
        ),
        "common_edit_tags": tags.most_common(12),
        "dimension_averages": dimension_averages,
        "section_type": _clean(section_type).casefold() if section_type else None,
        "funder_archetype": (
            _clean(funder_archetype).casefold() if funder_archetype else None
        ),
        "learning_policy": (
            "Only human-adjudicated APPROVE reviews become reusable examples. "
            "Award outcomes are retained as metadata and are not treated as causal proof."
        ),
    }
