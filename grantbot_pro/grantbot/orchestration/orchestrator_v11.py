from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from grantbot.applications.package_builder import build_application_package
from grantbot.automation.opportunity_pipeline import Opportunity
from grantbot.discovery.grants_gov import DEFAULT_KEYWORDS, discover
from grantbot.eligibility.applicant_role import classify_applicant_role
from grantbot.nofo.full_detail import get_full_nofo_intelligence


def _to_opportunity(item: dict[str, Any], full: Any) -> Opportunity:
    analysis = full.analysis or {}
    questions = analysis.get("application_questions", []) or []
    requirements = analysis.get("requirements", []) or []
    priorities = analysis.get("priorities", []) or []

    nofo_text = "\n".join(
        part
        for part in (
            full.title,
            full.opportunity_number,
            full.funder,
            "\n".join(str(x) for x in questions),
            "\n".join(str(x) for x in requirements),
            "\n".join(str(x) for x in priorities),
        )
        if part
    )

    return Opportunity(
        id=str(item.get("id", "")).strip(),
        title=str(item.get("title", full.title)).strip(),
        funder=str(item.get("funder", full.funder)).strip(),
        description="",
        eligibility="; ".join(full.eligibility),
        deadline=item.get("deadline"),
        amount=item.get("amount"),
        source_url=str(item.get("source_url", "")).strip(),
        nofo_text=nofo_text,
    )


def run_v11(
    *,
    keywords: list[str] | None = None,
    rows_per_keyword: int = 10,
    minimum_score: int = 60,
    maximum_direct_packages: int = 10,
    generate_drafts: bool = False,
    fetch_details: bool = True,
) -> dict[str, Any]:
    if not 1 <= rows_per_keyword <= 100:
        raise ValueError("rows_per_keyword must be between 1 and 100")

    if not 0 <= minimum_score <= 100:
        raise ValueError("minimum_score must be between 0 and 100")

    if not 1 <= maximum_direct_packages <= 50:
        raise ValueError("maximum_direct_packages must be between 1 and 50")

    active_keywords = [
        value.strip()
        for value in (keywords or DEFAULT_KEYWORDS)
        if value.strip()
    ]

    discovery = discover(
        keywords=active_keywords,
        rows_per_keyword=rows_per_keyword,
        fetch_details=fetch_details,
        generate_drafts=False,
    )

    direct_items: list[dict[str, Any]] = []
    partner_items: list[dict[str, Any]] = []
    rejected_items: list[dict[str, Any]] = []

    for item in discovery.results:
        score = int(item.get("score", 0))

        if item.get("hard_reject") or score < minimum_score:
            continue

        opportunity_id = str(item.get("id", "")).strip()

        if not opportunity_id:
            continue

        full = get_full_nofo_intelligence(opportunity_id)

        role = classify_applicant_role(
            eligibility=full.eligibility,
            existing_blockers=list(
                full.eligibility_gate.get("blockers", [])
            ),
        )

        record = {
            "opportunity_id": opportunity_id,
            "title": full.title or str(item.get("title", "")),
            "funder": full.funder or str(item.get("funder", "")),
            "score": max(score, int(full.analysis.get("fit_score", 0))),
            "priority": full.analysis.get(
                "priority",
                item.get("priority", ""),
            ),
            "deadline": item.get("deadline"),
            "amount": item.get("amount"),
            "source_url": item.get("source_url"),
            "cost_sharing": full.cost_sharing,
            "eligibility": full.eligibility,
            "applicant_role": role.to_dict(),
        }

        if role.role == "REJECT":
            rejected_items.append(record)
            continue

        if role.role in {"PARTNER_OR_SUBRECIPIENT", "VERIFY"}:
            partner_items.append(record)
            continue

        if len(direct_items) >= maximum_direct_packages:
            continue

        opportunity = _to_opportunity(item, full)

        package = build_application_package(
            opportunity,
            generate_drafts=generate_drafts,
        )

        record["package_id"] = package.package_id
        record["readiness_score"] = package.readiness_score
        record["status"] = package.status
        record["output_path"] = package.output_path

        direct_items.append(record)

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")

    partner_queue_path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "partner_queue"
        / f"partner_queue_{run_id}.json"
    )

    partner_queue_path.parent.mkdir(parents=True, exist_ok=True)

    partner_queue_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "created_at": now.isoformat(),
                "count": len(partner_items),
                "items": partner_items,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "run_id": run_id,
        "created_at": now.isoformat(),
        "keywords": active_keywords,
        "discovered_count": discovery.unique_hits,
        "direct_count": len(direct_items),
        "partner_count": len(partner_items),
        "rejected_count": len(rejected_items),
        "partner_queue_path": str(partner_queue_path),
        "direct_items": direct_items,
        "partner_items": partner_items,
        "rejected_items": rejected_items,
    }
