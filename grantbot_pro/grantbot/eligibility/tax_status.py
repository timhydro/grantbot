from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable


class TaxStatus(str, Enum):
    APPROVED_501C3 = "approved_501c3"
    PENDING_501C3 = "pending_501c3"
    FAITH_BASED = "faith_based"
    FISCAL_SPONSORED = "fiscal_sponsored"
    FOR_PROFIT = "for_profit"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TaxStatusEligibilityResult:
    eligible: bool
    route: str
    verification_required: bool
    hard_blocker: bool
    rationale: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_APPROVED_REQUIRED = (
    "501(c)(3) required",
    "501c3 required",
    "must be a 501(c)(3)",
    "current tax-exempt status",
    "irs determination letter required",
    "listed on the irs master file",
)
_PENDING_ALLOWED = (
    "pending 501(c)(3)",
    "pending 501c3",
    "determination pending",
    "determination letter pending",
    "not yet received a determination letter",
)
_FAITH_ALLOWED = (
    "faith-based organization",
    "faith based organization",
    "church or other faith-based",
    "religious organization eligible",
)
_FISCAL_SPONSOR_ALLOWED = (
    "fiscal sponsor",
    "fiscal sponsorship",
    "sponsored project",
)
_NO_501C3_REQUIRED = (
    "501(c)(3) not required",
    "501c3 not required",
    "tax-exempt status not required",
    "nonprofit status not required",
    "individuals and organizations",
)


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def evaluate_tax_status_eligibility(
    *,
    opportunity_text: str,
    applicant_status: TaxStatus,
    has_fiscal_sponsor: bool = False,
) -> TaxStatusEligibilityResult:
    """Evaluate tax-status compatibility without inventing eligibility.

    The function intentionally distinguishes a legal/tax-status hard blocker from
    a route that merely requires verification. This prevents pending nonprofits
    from being discarded when a funder permits faith-based applicants, pending
    determinations, fiscal sponsorship, or applicants that do not need 501(c)(3)
    recognition.
    """
    text = " ".join(str(opportunity_text).lower().split())

    no_501c3_required = _contains_any(text, _NO_501C3_REQUIRED)
    pending_allowed = _contains_any(text, _PENDING_ALLOWED)
    faith_allowed = _contains_any(text, _FAITH_ALLOWED)
    fiscal_allowed = _contains_any(text, _FISCAL_SPONSOR_ALLOWED)
    approved_required = _contains_any(text, _APPROVED_REQUIRED)

    if no_501c3_required:
        return TaxStatusEligibilityResult(
            True,
            "NO_501C3_REQUIRED",
            False,
            False,
            ["Opportunity explicitly indicates that approved 501(c)(3) status is not required."],
        )

    if applicant_status == TaxStatus.APPROVED_501C3:
        return TaxStatusEligibilityResult(
            True,
            "DIRECT_501C3",
            False,
            False,
            ["Applicant has approved 501(c)(3) status."],
        )

    if applicant_status == TaxStatus.PENDING_501C3:
        if pending_allowed:
            return TaxStatusEligibilityResult(
                True,
                "DIRECT_PENDING_501C3",
                True,
                False,
                ["Opportunity indicates that applicants with a pending IRS determination may proceed."],
            )
        if faith_allowed:
            return TaxStatusEligibilityResult(
                True,
                "FAITH_BASED_EXCEPTION",
                True,
                False,
                ["Opportunity separately permits church or faith-based applicants; verify the program-specific definition before submission."],
            )
        if fiscal_allowed and has_fiscal_sponsor:
            return TaxStatusEligibilityResult(
                True,
                "FISCAL_SPONSOR",
                True,
                False,
                ["Opportunity permits fiscal sponsorship and a fiscal sponsor is available."],
            )
        if fiscal_allowed:
            return TaxStatusEligibilityResult(
                False,
                "FISCAL_SPONSOR_NEEDED",
                True,
                False,
                ["Opportunity permits fiscal sponsorship, but no fiscal sponsor is currently recorded."],
            )
        if approved_required:
            return TaxStatusEligibilityResult(
                False,
                "WAIT_FOR_DETERMINATION",
                False,
                True,
                ["Opportunity explicitly requires current IRS-recognized 501(c)(3) status."],
            )
        return TaxStatusEligibilityResult(
            False,
            "VERIFY_PENDING_STATUS",
            True,
            False,
            ["The opportunity does not clearly state whether a pending 501(c)(3) applicant is accepted."],
        )

    if applicant_status == TaxStatus.FAITH_BASED and faith_allowed:
        return TaxStatusEligibilityResult(
            True,
            "FAITH_BASED_EXCEPTION",
            True,
            False,
            ["Opportunity explicitly includes faith-based organizations."],
        )

    if (applicant_status == TaxStatus.FISCAL_SPONSORED or has_fiscal_sponsor) and fiscal_allowed:
        return TaxStatusEligibilityResult(
            True,
            "FISCAL_SPONSOR",
            True,
            False,
            ["Opportunity permits fiscal sponsorship."],
        )

    if approved_required:
        return TaxStatusEligibilityResult(
            False,
            "501C3_REQUIRED",
            False,
            True,
            ["Opportunity explicitly requires approved 501(c)(3) status."],
        )

    return TaxStatusEligibilityResult(
        False,
        "VERIFY",
        True,
        False,
        ["Tax-status eligibility is not explicit and must be verified before application."],
    )
