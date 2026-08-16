from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass(frozen=True, slots=True)
class ApplicantRoleResult:
    role: str
    direct_applicant: bool
    partner_candidate: bool
    verification_required: bool
    blockers: list[str]
    rationale: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

NONPROFIT = (
    "nonprofit",
    "non-profit",
    "501(c)(3)",
    "501c3",
    "faith-based",
    "community-based",
)

GOVERNMENT = (
    "state governments",
    "county governments",
    "city or township governments",
    "special district governments",
    "public housing authorities",
    "tribal governments",
)

def classify_applicant_role(
    *,
    eligibility: list[str],
    existing_blockers: list[str] | None = None,
) -> ApplicantRoleResult:
    blockers = list(dict.fromkeys(existing_blockers or []))
    items = [str(x).strip().lower() for x in eligibility if str(x).strip()]

    if blockers:
        return ApplicantRoleResult(
            "REJECT", False, False, False, blockers,
            ["Existing eligibility or mission blockers require rejection."],
        )

    nonprofit = any(any(term in item for term in NONPROFIT) for item in items)
    government = any(any(term in item for term in GOVERNMENT) for item in items)
    others = any(
        "others" in item or "additional information on eligibility" in item
        for item in items
    )

    if nonprofit:
        return ApplicantRoleResult(
            "DIRECT_APPLICANT", True, True, False, [],
            ["Nonprofit eligibility is explicitly listed."],
        )

    if government and others:
        return ApplicantRoleResult(
            "PARTNER_OR_SUBRECIPIENT", False, True, True, [],
            [
                "Government or tribal applicants are explicitly listed.",
                "The Others category requires additional eligibility verification.",
                "Broken Growth should pursue this opportunity through an eligible prime applicant unless direct eligibility is verified.",
            ],
        )

    if government:
        return ApplicantRoleResult(
            "PARTNER_OR_SUBRECIPIENT", False, True, False, [],
            ["Government or tribal entities are the identified prime applicants."],
        )

    return ApplicantRoleResult(
        "VERIFY", False, False, True, [],
        ["Direct nonprofit eligibility has not been established."],
    )
