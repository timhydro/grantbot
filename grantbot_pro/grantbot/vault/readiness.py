from __future__ import annotations

from datetime import date, datetime
from typing import Any

from grantbot.vault.repository import (
    as_of_date,
    clean,
    list_documents,
    list_requirements,
)
from grantbot.vault.schema import REQUIREMENT_SCOPES


def _age_days(document: dict[str, Any], current: date) -> int | None:
    effective = clean(document.get("effective_date"))
    if effective:
        return max(0, (current - date.fromisoformat(effective)).days)
    created = clean(document.get("created_at"))
    if not created:
        return None
    try:
        created_date = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
    except ValueError:
        return None
    return max(0, (current - created_date).days)


def readiness_dashboard(
    *,
    scope: str = "GENERAL",
    as_of: str | None = None,
) -> dict[str, Any]:
    current = as_of_date(as_of)
    normalized_scope = clean(scope, max_length=80).upper() or "GENERAL"
    if normalized_scope not in REQUIREMENT_SCOPES:
        raise ValueError(f"Invalid scope: {normalized_scope}")
    requirements = list_requirements(scope=normalized_scope, active_only=True)
    documents = list_documents(current_only=True, as_of=current.isoformat())
    controls: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for requirement in requirements:
        matching = [
            document
            for document in documents
            if (
                requirement["document_key"]
                and document["document_key"] == requirement["document_key"]
            )
            or (
                not requirement["document_key"]
                and document["category"] == requirement["category"]
            )
        ]
        matching.sort(
            key=lambda item: (
                item["verification_state"] == "APPROVED",
                int(item["version"]),
            ),
            reverse=True,
        )
        selected = matching[0] if matching else None
        issues: list[str] = []
        if selected is None:
            issues.append("No current document satisfies this control")
        else:
            freshness = selected["freshness"]
            if freshness["state"] != "CURRENT":
                issues.append(f"Document freshness state is {freshness['state']}")
            if (
                bool(requirement["must_be_approved"])
                and selected["verification_state"] != "APPROVED"
            ):
                issues.append("Document is not APPROVED")
            max_age = requirement.get("max_age_days")
            age = _age_days(selected, current)
            if max_age is not None and age is not None and age > int(max_age):
                issues.append(
                    f"Document age {age} days exceeds configured maximum "
                    f"{int(max_age)} days"
                )
        if not issues:
            status = "SATISFIED"
        elif bool(requirement["required"]):
            status = "BLOCKED"
        else:
            status = "WARNING"
        item = {
            "requirement": requirement,
            "selected_document": selected,
            "status": status,
            "issues": issues,
        }
        controls.append(item)
        if status == "BLOCKED":
            blockers.append(item)
        elif status == "WARNING":
            warnings.append(item)

    current_documents = list_documents(current_only=True, as_of=current.isoformat())
    freshness_counts: dict[str, int] = {}
    for document in current_documents:
        state = str(document["freshness"]["state"])
        freshness_counts[state] = freshness_counts.get(state, 0) + 1

    return {
        "scope": normalized_scope,
        "as_of": current.isoformat(),
        "requirement_count": len(requirements),
        "required_count": sum(1 for item in requirements if item["required"]),
        "blocking_count": len(blockers),
        "warning_count": len(warnings),
        "ready": not blockers,
        "current_document_count": len(current_documents),
        "freshness_counts": freshness_counts,
        "controls": controls,
        "blockers": blockers,
        "warnings": warnings,
        "policy_note": (
            "Vault readiness evaluates only explicitly configured, source-backed "
            "document controls. GrantBot does not assume a document is universally "
            "required without a configured control."
        ),
    }
