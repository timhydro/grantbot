from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


TRUSTED_STATES = {"VERIFIED", "APPROVED"}
PLANNING_STATES = {"DRAFT", "PLANNING", "PLANNING_CONTEXT", "REASONABLE_PROJECTION"}


@dataclass(frozen=True, slots=True)
class EvidenceBrief:
    opportunity: dict[str, Any]
    verified_facts: list[dict[str, Any]]
    planning_context: list[dict[str, Any]]
    unknowns: list[dict[str, Any]]
    source_urls: list[str]
    evidence_strength: str
    research_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_fact(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(raw.get("key", raw.get("fact_key", raw.get("id", "")))).strip(),
        "value": raw.get("value", raw.get("answer")),
        "status": str(raw.get("status", raw.get("verification_state", "MISSING"))).strip().upper(),
        "source": str(raw.get("source", "unknown")).strip(),
        "source_url": str(raw.get("source_url", "")).strip(),
    }


def build_evidence_brief(*, opportunity: dict[str, Any], facts: list[dict[str, Any]]) -> EvidenceBrief:
    normalized = [_normalize_fact(item) for item in facts]
    verified = [
        item
        for item in normalized
        if item["status"] in TRUSTED_STATES and item["value"] not in (None, "", [], {})
    ]
    planning = [
        item
        for item in normalized
        if item["status"] in PLANNING_STATES and item["value"] not in (None, "", [], {})
    ]
    unknowns = [item for item in normalized if item not in verified and item not in planning]

    source_urls: list[str] = []
    official_url = str(opportunity.get("source_url") or "").strip()
    if official_url:
        source_urls.append(official_url)
    for item in verified:
        url = item.get("source_url") or ""
        if url and url not in source_urls:
            source_urls.append(url)

    if verified and official_url:
        strength = "STRONG"
    elif verified:
        strength = "MODERATE"
    else:
        strength = "INSUFFICIENT"

    actions: list[str] = []
    if not official_url:
        actions.append("Locate and verify the official funder opportunity source.")
    if not str(opportunity.get("eligibility") or "").strip():
        actions.append("Extract applicant eligibility directly from the official source.")
    if not str(opportunity.get("deadline") or "").strip():
        actions.append("Verify the deadline or confirm that the opportunity is rolling/open-ended.")
    if unknowns:
        actions.append("Resolve unknown organization facts before using them in a narrative or budget.")
    if not verified:
        actions.append("Load verified organization facts from the canonical knowledge base before drafting.")
    if not actions:
        actions.append("Proceed to strategy and writing while preserving source provenance for every factual claim.")

    opportunity_summary = {
        key: opportunity.get(key)
        for key in (
            "title",
            "funder",
            "agency",
            "description",
            "eligibility",
            "deadline",
            "source_url",
            "opportunity_type",
        )
        if opportunity.get(key) not in (None, "")
    }
    return EvidenceBrief(
        opportunity=opportunity_summary,
        verified_facts=verified,
        planning_context=planning,
        unknowns=unknowns,
        source_urls=source_urls,
        evidence_strength=strength,
        research_actions=actions,
    )
