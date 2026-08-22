from __future__ import annotations

import time
from typing import Any, Mapping

from grantbot.agents.adversarial_panel_v30 import run_adversarial_panel
from grantbot.intelligence.adaptive_v30 import (
    consistency_audit,
    intelligence_status,
    record_model_run,
    sentence_provenance,
)
from grantbot.knowledge.canonical import current_facts
from grantbot.production.master_tool import production_status as v29_production_status
from grantbot.production.master_tool import run_application_answer as run_v29_application_answer


TRUSTED_FACT_STATES = ["VERIFIED", "APPROVED"]


def production_status_v30() -> dict[str, Any]:
    return {
        "version": "30.0.0",
        "base_production": v29_production_status(),
        "adaptive_intelligence": intelligence_status(),
        "automatic_sentence_provenance": True,
        "automatic_model_run_telemetry": True,
        "optional_adversarial_panel": True,
        "optional_budget_workplan_consistency": True,
        "single_master_writer": True,
        "human_review_required": True,
        "external_submission_enabled": False,
        "safe_to_submit": False,
    }


def _record_role_telemetry(
    *,
    role_models: Mapping[str, Mapping[str, Any]],
    task_type: str,
    success: bool,
    elapsed_ms: float,
    artifact_sha256: str | None,
) -> list[int]:
    ids: list[int] = []
    role_count = max(1, len(role_models))
    proportional_latency = elapsed_ms / role_count
    for role, runtime in role_models.items():
        if role not in {"research", "eligibility", "strategy", "writing", "red_team", "grant_quality", "readiness"}:
            continue
        normalized_role = "red_team" if role == "grant_quality" else role
        provider = str(runtime.get("provider") or "unknown").strip()
        model = str(runtime.get("model") or "unknown").strip()
        if not provider or not model:
            continue
        record_id = record_model_run(
            role=normalized_role,
            provider=provider,
            model=model,
            task_type=task_type,
            success=success,
            latency_ms=proportional_latency,
            metadata={
                "source": "v30-production-run",
                "artifact_sha256": artifact_sha256,
                "latency_is_proportional_estimate": True,
                "quality_score_recorded": False,
                "cost_recorded": False,
            },
        )
        ids.append(record_id)
    return ids


def run_adaptive_application_answer(
    *,
    dossier: str,
    question: str,
    max_words: int | None = None,
    section_type: str = "general",
    funder_archetype: str = "general",
    budget: Mapping[str, float] | None = None,
    workplan: Mapping[str, Any] | None = None,
    expected_budget_total: float | None = None,
    run_adversarial_review: bool = False,
) -> dict[str, Any]:
    if not dossier.strip():
        raise ValueError("dossier cannot be empty")
    if not question.strip():
        raise ValueError("question cannot be empty")
    if max_words is not None and max_words <= 0:
        raise ValueError("max_words must be positive when supplied")
    if expected_budget_total is not None and expected_budget_total < 0:
        raise ValueError("expected_budget_total cannot be negative")
    if (budget is None) != (workplan is None):
        raise ValueError("budget and workplan must be supplied together for consistency auditing")

    started = time.perf_counter()
    base = run_v29_application_answer(
        dossier=dossier,
        question=question,
        max_words=max_words,
        section_type=section_type,
        funder_archetype=funder_archetype,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    final_answer = str(base.get("final_answer") or "").strip()
    status = str(base.get("status") or "REMEDIATION_REQUIRED").strip()
    success = status == "READY_FOR_HUMAN_REVIEW" and bool(final_answer)
    role_models = base.get("role_models") if isinstance(base.get("role_models"), dict) else {}
    artifact_sha256 = str(base.get("artifact_sha256") or "").strip() or None

    facts = current_facts(verification_states=TRUSTED_FACT_STATES)
    provenance = (
        [item.to_dict() for item in sentence_provenance(text=final_answer, facts=facts)]
        if final_answer
        else []
    )
    unresolved_provenance = [
        item
        for item in provenance
        if item["support_status"] in {"PARTIAL", "UNSUPPORTED", "UNRESOLVED"}
    ]

    consistency_items: list[dict[str, Any]] = []
    if budget is not None and workplan is not None:
        consistency_items = [
            item.to_dict()
            for item in consistency_audit(
                narrative=final_answer,
                budget=budget,
                workplan=workplan,
                expected_total=expected_budget_total,
            )
        ]

    adversarial: dict[str, Any] | None = None
    if run_adversarial_review and final_answer:
        adversarial = run_adversarial_panel(
            dossier=dossier,
            final_answer=final_answer,
            budget_context={
                "budget": dict(budget or {}),
                "workplan": dict(workplan or {}),
                "expected_budget_total": expected_budget_total,
            },
        ).to_dict()

    telemetry_ids = _record_role_telemetry(
        role_models=role_models,
        task_type=section_type,
        success=success,
        elapsed_ms=elapsed_ms,
        artifact_sha256=artifact_sha256,
    )

    blockers: list[str] = []
    if unresolved_provenance:
        blockers.append(
            f"{len(unresolved_provenance)} sentence(s) require provenance review before approval."
        )
    blocking_consistency = [item for item in consistency_items if item["severity"] == "BLOCKER"]
    if blocking_consistency:
        blockers.append(
            f"{len(blocking_consistency)} budget/workplan consistency blocker(s) require remediation."
        )
    if adversarial and adversarial.get("status") == "REMEDIATION_REQUIRED":
        blockers.append("Adversarial review panel requires remediation.")

    adaptive_status = "READY_FOR_HUMAN_REVIEW" if success and not blockers else "REMEDIATION_REQUIRED"
    return {
        **base,
        "version": "30.0.0",
        "adaptive_status": adaptive_status,
        "elapsed_ms": round(elapsed_ms, 2),
        "sentence_provenance": provenance,
        "provenance_unresolved_count": len(unresolved_provenance),
        "consistency_issues": consistency_items,
        "adversarial_review": adversarial,
        "adaptive_blockers": blockers,
        "telemetry_record_ids": telemetry_ids,
        "human_review_required": True,
        "submission_performed": False,
        "safe_to_submit": False,
    }
