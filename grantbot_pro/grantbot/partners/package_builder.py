from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from grantbot.eligibility.applicant_role import classify_applicant_role
from grantbot.nofo.full_detail import get_full_nofo_intelligence

def build_partner_package(opportunity_id: str) -> dict[str, Any]:
    full = get_full_nofo_intelligence(opportunity_id)
    role = classify_applicant_role(
        eligibility=full.eligibility,
        existing_blockers=list(full.eligibility_gate.get("blockers", [])),
    )
    if role.role == "REJECT":
        raise ValueError("Opportunity rejected by eligibility/mission gate")
    if role.role == "DIRECT_APPLICANT":
        raise ValueError("Use direct application pipeline for this opportunity")

    root = Path(__file__).resolve().parents[2] / "data" / "partner_packages" / str(opportunity_id)
    root.mkdir(parents=True, exist_ok=True)

    joined = " ".join(full.eligibility).lower()
    primes: list[str] = []
    for signal, label in (
        ("county governments", "County government"),
        ("city or township governments", "City or township government"),
        ("state governments", "State government"),
        ("special district governments", "Special district government"),
        ("public housing authorities", "Public housing authority"),
        ("tribal governments", "Eligible tribal government"),
    ):
        if signal in joined and label not in primes:
            primes.append(label)
    if not primes:
        primes = ["Eligible prime applicant identified in official NOFO"]

    bgm_role = [
        "Reentry-focused housing stability and supportive housing services",
        "Employment placement, workforce development, and job-readiness support",
        "Case management and resource navigation",
        "Mentorship, life-skills development, and supportive-community programming",
        "Participant transition and stabilization support",
        "Outcome tracking for housing stability, employment retention, and successful reentry",
    ]
    missing: list[str] = []
    if role.verification_required:
        missing.append("Verify official NOFO clarification for the 'Others' eligibility category")
    if full.cost_sharing is True:
        missing.append("Confirm prime applicant match/cost-sharing plan and Broken Growth contribution, if any")

    readiness = max(0, 100 - len(missing) * 10 - (5 if role.role == "PARTNER_OR_SUBRECIPIENT" else 20))
    package = {
        "opportunity_id": str(opportunity_id),
        "title": full.title,
        "funder": full.funder,
        "applicant_role": role.to_dict(),
        "cost_sharing": full.cost_sharing,
        "readiness_score": readiness,
        "missing_information": missing,
        "recommended_prime_types": primes,
        "proposed_bgm_role": bgm_role,
        "package_path": str(root / "partner_package.json"),
        "concept_summary_path": str(root / "concept_summary.md"),
        "scope_of_work_path": str(root / "scope_of_work.md"),
        "outreach_pitch_path": str(root / "outreach_pitch.md"),
    }
    (root / "partner_package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    (root / "concept_summary.md").write_text(
        "\n".join([
            f"# Partner Concept Summary — {full.title}",
            "",
            f"**Funder:** {full.funder}",
            f"**Applicant Role:** {role.role}",
            f"**Readiness Score:** {readiness}/100",
            f"**Cost Sharing:** {full.cost_sharing}",
            "",
            "## Recommended Prime Applicant Types",
            *[f"- {x}" for x in primes],
            "",
            "## Proposed Broken Growth Role",
            *[f"- {x}" for x in bgm_role],
            "",
            "## Missing Information",
            *([f"- {x}" for x in missing] if missing else ["- None currently identified"]),
            "",
        ]),
        encoding="utf-8",
    )
    (root / "scope_of_work.md").write_text(
        "\n".join([
            f"# Proposed Scope of Work — {full.title}",
            "",
            "BrokenGrowthMinistries would serve as a partner or subrecipient under an eligible prime applicant.",
            "",
            "## Core Responsibilities",
            *[f"- {x}" for x in bgm_role],
            "",
            "Final deliverables, budget, reporting requirements, data-sharing rules, and performance targets must be approved by the eligible prime applicant.",
            "",
        ]),
        encoding="utf-8",
    )
    (root / "outreach_pitch.md").write_text(
        "\n".join([
            f"# Partner Outreach Pitch — {full.title}",
            "",
            f"BrokenGrowthMinistries is seeking to collaborate with an eligible prime applicant pursuing {full.title}.",
            "",
            "Our proposed contribution is a reentry-focused service-delivery role combining housing stability, workforce development, case management, resource navigation, mentorship, and participant support.",
            "",
            "We are prepared to define a compliant subrecipient or service-provider scope aligned with the prime applicant's program design, budget, reporting requirements, and required outcomes.",
            "",
        ]),
        encoding="utf-8",
    )
    return package

def load_partner_package(opportunity_id: str) -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "data" / "partner_packages" / str(opportunity_id) / "partner_package.json"
    if not path.exists():
        raise FileNotFoundError(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Invalid stored partner package")
    return data
