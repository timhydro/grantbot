from __future__ import annotations

from typing import Any

from grantbot.budget.workspace import budget_consistency, latest_budget
from grantbot.core.database import connection, utc_now
from grantbot.packaging import packet_guard_v19 as base


build_packet = base.build_packet
controlled_upload_path = base.controlled_upload_path
get_packet = base.get_packet
register_attachment = base.register_attachment
verify_attachment = base.verify_attachment


def _ensure_binding_schema() -> None:
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS packet_budget_bindings_v20 (
                packet_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                budget_id TEXT NOT NULL,
                budget_sha256 TEXT NOT NULL,
                budget_version INTEGER NOT NULL,
                budget_approved INTEGER NOT NULL,
                bound_at TEXT NOT NULL
            )
            """
        )


def _binding(packet_id: str) -> dict[str, Any] | None:
    _ensure_binding_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM packet_budget_bindings_v20 WHERE packet_id=?",
            (packet_id,),
        ).fetchone()
    return None if row is None else dict(row)


def _budget_identity(workspace_id: str) -> dict[str, Any]:
    latest = latest_budget(workspace_id)
    if latest is None:
        return {
            "budget_id": "",
            "budget_sha256": "",
            "budget_version": 0,
            "budget_approved": 0,
        }
    return {
        "budget_id": str(latest["budget_id"]),
        "budget_sha256": str(latest["calculation_sha256"]),
        "budget_version": int(latest["version"]),
        "budget_approved": int(bool(latest["approved"])),
    }


def approve_packet(
    packet_id: str,
    *,
    actor: str,
    note: str,
) -> dict[str, Any]:
    packet = get_packet(packet_id)
    workspace_id = str(packet["workspace_id"])
    gate = budget_consistency(workspace_id)
    if gate["blockers"]:
        raise ValueError(
            "Budget consistency blockers must be resolved before packet approval: "
            + "; ".join(gate["blockers"])
        )
    identity = _budget_identity(workspace_id)
    approved = base.approve_packet(packet_id, actor=actor, note=note)
    _ensure_binding_schema()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO packet_budget_bindings_v20(
                packet_id, workspace_id, budget_id, budget_sha256,
                budget_version, budget_approved, bound_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(packet_id) DO UPDATE SET
                workspace_id=excluded.workspace_id,
                budget_id=excluded.budget_id,
                budget_sha256=excluded.budget_sha256,
                budget_version=excluded.budget_version,
                budget_approved=excluded.budget_approved,
                bound_at=excluded.bound_at
            """,
            (
                packet_id,
                workspace_id,
                identity["budget_id"],
                identity["budget_sha256"],
                identity["budget_version"],
                identity["budget_approved"],
                utc_now(),
            ),
        )
    return approved


def _binding_issues(packet_id: str) -> list[str]:
    packet = get_packet(packet_id)
    workspace_id = str(packet["workspace_id"])
    binding = _binding(packet_id)
    if binding is None:
        return ["Packet budget binding is missing"]
    current = _budget_identity(workspace_id)
    issues: list[str] = []
    for field in (
        "budget_id",
        "budget_sha256",
        "budget_version",
        "budget_approved",
    ):
        if str(binding[field]) != str(current[field]):
            issues.append(
                "Budget changed after packet approval; create a new packet revision"
            )
            break
    return issues


def finalize_packet(packet_id: str, *, actor: str) -> dict[str, Any]:
    packet = get_packet(packet_id)
    workspace_id = str(packet["workspace_id"])
    budget_gate = budget_consistency(workspace_id)
    issues = list(budget_gate["blockers"])
    issues.extend(_binding_issues(packet_id))
    if issues:
        raise ValueError("; ".join(dict.fromkeys(issues)))

    # Final sealing is subordinate to the complete Master gate, which also
    # checks human approval, lifecycle stage, risks, authoritative
    # requirements, narratives, and budget consistency.
    from grantbot.master.service import submission_gate

    master_gate = submission_gate(workspace_id)
    if not master_gate["ready_for_submission"]:
        raise ValueError(
            "Master submission gate blocked packet sealing: "
            + "; ".join(master_gate["blockers"])
        )
    return base.finalize_packet(packet_id, actor=actor)


def verify_packet_integrity(packet_id: str) -> dict[str, Any]:
    result = base.verify_packet_integrity(packet_id)
    budget_issues = _binding_issues(packet_id)
    result["budget_binding"] = _binding(packet_id)
    result["issues"] = list(
        dict.fromkeys(list(result.get("issues", [])) + budget_issues)
    )
    result["safe"] = not result["issues"]
    result["submission_enabled"] = False
    return result
