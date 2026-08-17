from __future__ import annotations

import importlib.util
from collections import Counter
from typing import Any

from grantbot.core.database import health_check, initialize_database
from grantbot.master.database import feedback_rows, initialize_master_schema
from grantbot.knowledge.canonical import conflicts as canonical_conflicts, migrate_legacy_facts
from grantbot.review.staging_v17 import get_workspace, health as staging_health


VERSION_MODULES = {
    "v5": "grantbot.api.master_pipeline_v5",
    "v6": "grantbot.api.discovery_v6",
    "v7": "grantbot.api.application_v7",
    "v8": "grantbot.api.orchestrator_v8",
    "v9": "grantbot.api.nofo_v9",
    "v10": "grantbot.api.applicant_role_v10",
    "v11": "grantbot.api.orchestrator_v11",
    "v12": "grantbot.api.partners_v12",
    "v13": "grantbot.api.nofo_v13",
    "v14": "grantbot.api.matching_v14",
    "v15": "grantbot.api.readiness_v15",
    "v16": "grantbot.api.live_queue_v16",
    "v17": "grantbot.api.staging_v17",
    "v18": "grantbot.api.application_writer_v18",
    "v19": "grantbot.api.packet_v19",
    "master": "grantbot.api.master",
}


def system_versions() -> dict[str, Any]:
    versions = {
        version: {
            "module": module,
            "available": importlib.util.find_spec(module) is not None,
        }
        for version, module in VERSION_MODULES.items()
    }
    return {
        "versions": versions,
        "all_available": all(item["available"] for item in versions.values()),
        "submission_enabled": False,
    }


def health() -> dict[str, Any]:
    initialize_database()
    initialize_master_schema()
    migration = migrate_legacy_facts()
    database = health_check()
    staging = staging_health()
    versions = system_versions()
    return {
        "healthy": bool(database.get("healthy")) and bool(staging.get("healthy", True)),
        "database": database,
        "canonical_fact_migration": migration,
        "canonical_fact_conflicts": canonical_conflicts(),
        "staging_v17": staging,
        "versions": versions,
        "human_approval_required": True,
        "submission_enabled": False,
    }


def submission_gate(workspace_id: str) -> dict[str, Any]:
    workspace = get_workspace(workspace_id)
    blockers: list[str] = []
    if not workspace.get("human_approved"):
        blockers.append("application lacks human approval")
    if workspace.get("stage") != "READY_FOR_SUBMISSION":
        blockers.append("workspace is not READY_FOR_SUBMISSION")
    open_risks = [item for item in workspace.get("risks", []) if item.get("status") == "OPEN"]
    if open_risks:
        blockers.append(f"{len(open_risks)} unresolved compliance risk(s)")
    pending = [item for item in workspace.get("checklist", []) if item.get("status") == "PENDING"]
    if pending:
        blockers.append(f"{len(pending)} pending checklist item(s)")
    drafts = workspace.get("writer_tasks", [])
    incomplete = [
        item for item in drafts
        if item.get("status") not in {"READY_FOR_REVIEW", "APPROVED"} or not str(item.get("response", "")).strip()
    ]
    if incomplete:
        blockers.append(f"{len(incomplete)} narrative task(s) not review-ready")
    return {
        "workspace_id": workspace_id,
        "ready_for_submission": not blockers,
        "blockers": blockers,
        "human_approval_required": True,
        "submission_enabled": False,
    }


def learning_profile() -> dict[str, Any]:
    rows = feedback_rows()
    accepted = [row for row in rows if row["accepted"]]
    tags = Counter(tag for row in accepted for tag in row.get("edit_tags", []))
    section_counts = Counter(row["section_type"] for row in accepted)
    funder_counts = Counter(row["funder_archetype"] for row in accepted)
    scores = [
        float(row["reviewer_score"])
        for row in accepted
        if row.get("reviewer_score") is not None
    ]
    return {
        "feedback_count": len(rows),
        "accepted_count": len(accepted),
        "acceptance_rate": round(len(accepted) / len(rows), 4) if rows else 0.0,
        "average_reviewer_score": round(sum(scores) / len(scores), 2) if scores else None,
        "common_edit_tags": tags.most_common(10),
        "accepted_sections": section_counts.most_common(),
        "accepted_funder_archetypes": funder_counts.most_common(),
    }
