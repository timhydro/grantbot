from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from grantbot.applications.review_workspace import (
    ReviewField,
    ReviewStatus,
    new_review_packet,
    save_review_packet,
)
from grantbot.eligibility.tax_status import (
    TaxStatus,
    evaluate_tax_status_eligibility,
)


@dataclass(frozen=True, slots=True)
class ReviewRoute:
    should_create: bool
    status: ReviewStatus
    funding_type: str
    tax_route: str
    rationale: list[str]


def classify_funding_type(text: str, metadata: dict[str, Any] | None = None) -> str:
    blob = " ".join((text, str(metadata or {}))).lower()
    if any(term in blob for term in ("angel investor", "equity", "venture", "impact investor")):
        return "IMPACT_OR_ANGEL_INVESTMENT"
    if any(term in blob for term in ("program-related investment", "pri", "recoverable grant")):
        return "PRI_OR_RECOVERABLE_CAPITAL"
    if any(term in blob for term in ("fiscal sponsor", "fiscal sponsorship")):
        return "FISCAL_SPONSORSHIP"
    if any(term in blob for term in ("cdfi", "community development financial institution")):
        return "CDFI_LOAN"
    if any(term in blob for term in ("microloan", "loan", "financing", "line of credit")):
        return "LOAN"
    if any(term in blob for term in ("crowdfund", "crowdfunding", "kiva")):
        return "CROWDFUNDING"
    if any(term in blob for term in ("sponsor", "sponsorship")):
        return "CORPORATE_SPONSORSHIP"
    if any(term in blob for term in ("in-kind", "equipment donation", "product donation")):
        return "IN_KIND"
    return "GRANT"


def route_for_review(
    analyzed: dict[str, Any],
    *,
    applicant_status: TaxStatus = TaxStatus.PENDING_501C3,
    has_fiscal_sponsor: bool = False,
    minimum_score: int = 60,
) -> ReviewRoute:
    score = int(analyzed.get("score", 0) or 0)
    if analyzed.get("hard_reject") or score < minimum_score:
        return ReviewRoute(False, ReviewStatus.INELIGIBLE, "UNKNOWN", "REJECT", ["Below pursuit threshold or hard-rejected."])

    nofo = analyzed.get("nofo") or {}
    text = " ".join(
        str(x)
        for x in (
            analyzed.get("title", ""),
            analyzed.get("funder", ""),
            nofo.get("eligibility", "") if isinstance(nofo, dict) else "",
            nofo.get("requirements", "") if isinstance(nofo, dict) else "",
            nofo.get("raw_text", "") if isinstance(nofo, dict) else "",
        )
    )
    tax = evaluate_tax_status_eligibility(
        opportunity_text=text,
        applicant_status=applicant_status,
        has_fiscal_sponsor=has_fiscal_sponsor,
    )
    funding_type = classify_funding_type(text, analyzed)

    if tax.hard_blocker:
        return ReviewRoute(True, ReviewStatus.HOLD, funding_type, tax.route, tax.rationale)
    if tax.verification_required:
        return ReviewRoute(True, ReviewStatus.NEEDS_USER, funding_type, tax.route, tax.rationale)
    return ReviewRoute(True, ReviewStatus.READY_FOR_REVIEW, funding_type, tax.route, tax.rationale)


def create_review_folder_from_analysis(
    analyzed: dict[str, Any],
    *,
    applicant_status: TaxStatus = TaxStatus.PENDING_501C3,
    has_fiscal_sponsor: bool = False,
    minimum_score: int = 60,
) -> str | None:
    route = route_for_review(
        analyzed,
        applicant_status=applicant_status,
        has_fiscal_sponsor=has_fiscal_sponsor,
        minimum_score=minimum_score,
    )
    if not route.should_create:
        return None

    missing = list(analyzed.get("missing_information", []) or [])
    if route.status in {ReviewStatus.NEEDS_USER, ReviewStatus.HOLD}:
        missing.append(f"Tax-status route requires review: {route.tax_route}")

    fields = [
        ReviewField("Opportunity", str(analyzed.get("title", "")), "opportunity analysis"),
        ReviewField("Funder", str(analyzed.get("funder", "")), "opportunity analysis"),
        ReviewField("Funding type", route.funding_type, "GrantBot classifier"),
        ReviewField("Tax-status route", route.tax_route, "GrantBot eligibility engine", route.status != ReviewStatus.READY_FOR_REVIEW),
        ReviewField("Score", str(analyzed.get("score", 0)), "GrantBot scoring"),
        ReviewField("Deadline", str(analyzed.get("deadline") or "Not stated"), "opportunity analysis"),
        ReviewField("Amount", str(analyzed.get("amount") or "To be determined"), "opportunity analysis", True),
    ]

    packet = new_review_packet(
        opportunity_id=str(analyzed.get("id") or analyzed.get("title") or "opportunity"),
        opportunity_name=str(analyzed.get("title") or "Funding opportunity"),
        funding_type=route.funding_type,
        source_url=str(analyzed.get("source_url") or ""),
        fields=fields,
        missing_items=list(dict.fromkeys(str(x) for x in missing if str(x).strip())),
        submission_steps=[
            "Review GrantBot's eligibility and funding-type classification.",
            "Confirm every human-required legal, financial, credential, banking, signature, and attestation field.",
            "Generate or complete the application narrative and budget using verified facts only.",
            "Mark READY_TO_SUBMIT only after authorized human review.",
            "Submit through the funder's official portal or authorized channel.",
        ],
        notes=list(route.rationale),
        deadline=str(analyzed.get("deadline") or "") or None,
        requested_amount=str(analyzed.get("amount") or "") or None,
        status=route.status,
    )
    return str(save_review_packet(packet))
