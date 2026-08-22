from __future__ import annotations

from typing import Any

PLANNING_STATES = {"UNVERIFIED", "DRAFT"}


def _writer_status(verification_state: str) -> str:
    normalized = str(verification_state or "MISSING").strip().upper()
    if normalized in PLANNING_STATES:
        return "DRAFT"
    if normalized in {"VERIFIED", "APPROVED", "MISSING"}:
        return normalized
    return "MISSING"


def load_canonical_writer_facts(
    *,
    actor: str = "canonical-writer-facts",
) -> list[dict[str, Any]]:
    """Return the single canonical fact set in the legacy writer shape.

    Older GrantBot paths loaded a flat demonstration JSON file and implicitly
    upgraded every value in it to APPROVED. That made sample projections usable
    as applicant facts. All writing and application paths now call this adapter,
    which preserves canonical verification state and provenance.
    """

    # Keep these imports lazy. During application startup, canonical.py imports
    # grantbot.master.database; importing the full knowledge stack at module load
    # would make grantbot.master.__init__ re-enter canonical.py.
    from grantbot.knowledge.canonical import current_facts
    from grantbot.knowledge.integrity_v23 import prepare_canonical_knowledge

    prepare_canonical_knowledge(actor=actor)
    output: list[dict[str, Any]] = []
    for raw in current_facts():
        key = str(raw.get("fact_key") or "").strip().lower()
        if not key:
            continue
        verification_state = str(
            raw.get("verification_state") or "MISSING"
        ).strip().upper()
        output.append(
            {
                "id": str(raw.get("fact_id") or ""),
                "category": str(raw.get("category") or "general").strip().lower(),
                "key": key,
                "value": raw.get("value"),
                "status": _writer_status(verification_state),
                "verification_state": verification_state,
                "source": str(raw.get("source") or "unspecified"),
                "source_type": str(raw.get("source_type") or ""),
                "confidence": float(raw.get("confidence") or 0.0),
                "notes": str(raw.get("notes") or ""),
            }
        )
    return output
