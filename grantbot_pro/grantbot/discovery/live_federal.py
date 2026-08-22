from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from grantbot.automation.opportunity_pipeline import analyze_opportunity
from grantbot.discovery.grants_gov import (
    DEFAULT_KEYWORDS,
    fetch_opportunity,
    normalize_opportunity,
    search_keyword,
)
from grantbot.discovery.status_guard import (
    OpportunityState,
    evaluate_opportunity_status,
    parse_deadline,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "live_federal" / "latest.json"
)


@dataclass(frozen=True, slots=True)
class LiveSweepSummary:
    keywords: list[str]
    raw_hits: int
    unique_hits: int
    detailed_hits: int
    active: int
    forecasted: int
    quarantined: int
    closed: int
    review_required: int
    errors: int
    output_file: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    temp.chmod(0o600)
    temp.replace(path)
    path.chmod(0o600)


def _result_sort_key(
    item: dict[str, Any],
) -> tuple[int, int, int, str]:
    state_rank = {
        OpportunityState.ACTIVE.value: 0,
        OpportunityState.FORECASTED.value: 1,
        OpportunityState.REVIEW_REQUIRED.value: 2,
        OpportunityState.QUARANTINED.value: 3,
        OpportunityState.CLOSED.value: 4,
        "ERROR": 5,
    }

    return (
        state_rank.get(str(item.get("live_status", "")), 9),
        1 if item.get("hard_reject") else 0,
        -int(item.get("score", 0) or 0),
        str(item.get("title", "")).lower(),
    )


def _candidate_sort_key(
    item: tuple[str, dict[str, Any]],
    hit_keywords: dict[str, set[str]],
) -> tuple[int, int, int, str]:
    oid, hit = item
    status = str(hit.get("oppStatus") or "").strip().upper()
    status_rank = 0 if status == "POSTED" else 1
    matched_keyword_rank = -len(hit_keywords.get(oid, set()))

    deadline = parse_deadline(hit.get("closeDate"))
    deadline_rank = (
        deadline.toordinal()
        if deadline is not None
        else 9_999_999
    )

    return (
        status_rank,
        matched_keyword_rank,
        deadline_rank,
        str(hit.get("title", "")).lower(),
    )


def _blocked_result(
    *,
    hit: dict[str, Any],
    decision: dict[str, Any],
    matched_keywords: list[str],
) -> dict[str, Any]:
    return {
        "id": str(hit.get("id", "")),
        "title": str(hit.get("title", "")),
        "funder": str(
            hit.get("agencyName")
            or hit.get("agencyCode")
            or ""
        ),
        "score": 0,
        "priority": "REJECT",
        "hard_reject": True,
        "blockers": list(decision.get("reasons", [])),
        "deadline": hit.get("closeDate"),
        "amount": None,
        "source_url": (
            "https://www.grants.gov/search-results-detail/"
            + str(hit.get("id", ""))
        ),
        "matched_domains": [],
        "missing_information": [],
        "readiness_score": 0,
        "writer_packages": [],
        "live_status": decision.get("state"),
        "status_guard": decision,
        "matched_keywords": matched_keywords,
        "opportunity_number": hit.get("number"),
        "submission_allowed": False,
    }


def run_live_sweep(
    *,
    keywords: list[str] | None = None,
    rows_per_keyword: int = 20,
    max_details: int = 60,
    verify_authority: bool = True,
    output_path: Path = DEFAULT_OUTPUT,
) -> tuple[LiveSweepSummary, list[dict[str, Any]]]:
    selected_keywords = [
        value.strip()
        for value in (keywords or DEFAULT_KEYWORDS)
        if value.strip()
    ]

    if not selected_keywords:
        raise ValueError("At least one keyword is required.")

    if rows_per_keyword < 1 or rows_per_keyword > 100:
        raise ValueError(
            "rows_per_keyword must be between 1 and 100."
        )

    if max_details < 1 or max_details > 500:
        raise ValueError(
            "max_details must be between 1 and 500."
        )

    unique_hits: dict[str, dict[str, Any]] = {}
    hit_keywords: dict[str, set[str]] = {}
    raw_hits = 0

    for keyword in selected_keywords:
        hits = search_keyword(
            keyword,
            rows=rows_per_keyword,
            statuses="posted|forecasted",
        )
        raw_hits += len(hits)

        for hit in hits:
            oid = str(hit.get("id", "")).strip()

            if not oid:
                continue

            unique_hits.setdefault(oid, hit)
            hit_keywords.setdefault(oid, set()).add(keyword)

    results: list[dict[str, Any]] = []
    errors = 0

    ordered_hits = sorted(
        unique_hits.items(),
        key=lambda item: _candidate_sort_key(
            item,
            hit_keywords,
        ),
    )[:max_details]

    for oid, hit in ordered_hits:
        matched = sorted(hit_keywords.get(oid, set()))

        try:
            detail = fetch_opportunity(oid)
            status = evaluate_opportunity_status(
                hit=hit,
                detail=detail,
                verify_authority=verify_authority,
            )
            status_dict = status.to_dict()

            if not status.drafting_allowed:
                results.append(
                    _blocked_result(
                        hit=hit,
                        decision=status_dict,
                        matched_keywords=matched,
                    )
                )
                continue

            opportunity = normalize_opportunity(hit, detail)
            analyzed = analyze_opportunity(
                opportunity,
                generate_drafts=False,
            )
            analyzed["live_status"] = status.state
            analyzed["status_guard"] = status_dict
            analyzed["matched_keywords"] = matched
            analyzed["opportunity_number"] = (
                opportunity.metadata.get("opportunity_number")
            )
            analyzed["submission_allowed"] = False
            results.append(analyzed)

        except Exception as exc:
            errors += 1
            results.append(
                {
                    "id": oid,
                    "title": str(hit.get("title", "")),
                    "score": 0,
                    "priority": "REVIEW",
                    "hard_reject": True,
                    "blockers": [
                        f"{type(exc).__name__}: {exc}"
                    ],
                    "live_status": "ERROR",
                    "matched_keywords": matched,
                    "opportunity_number": hit.get("number"),
                    "submission_allowed": False,
                }
            )

    results.sort(key=_result_sort_key)

    state_counts = {
        state.value: sum(
            1
            for item in results
            if item.get("live_status") == state.value
        )
        for state in OpportunityState
    }

    payload = {
        "generated_at": _now(),
        "human_review_required": True,
        "auto_submission": False,
        "keywords": selected_keywords,
        "raw_hits": raw_hits,
        "unique_hits": len(unique_hits),
        "detailed_hits": len(ordered_hits),
        "results": results,
    }

    _write_json(output_path, payload)

    history_dir = output_path.parent / "history"
    timestamp_name = datetime.now().astimezone().strftime(
        "%Y%m%d_%H%M%S"
    )
    _write_json(
        history_dir / f"federal_sweep_{timestamp_name}.json",
        payload,
    )

    summary = LiveSweepSummary(
        keywords=selected_keywords,
        raw_hits=raw_hits,
        unique_hits=len(unique_hits),
        detailed_hits=len(ordered_hits),
        active=state_counts[OpportunityState.ACTIVE.value],
        forecasted=state_counts[
            OpportunityState.FORECASTED.value
        ],
        quarantined=state_counts[
            OpportunityState.QUARANTINED.value
        ],
        closed=state_counts[OpportunityState.CLOSED.value],
        review_required=state_counts[
            OpportunityState.REVIEW_REQUIRED.value
        ],
        errors=errors,
        output_file=str(output_path),
    )

    return summary, results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grantbot-live-federal",
        description=(
            "Run a live Grants.gov funding sweep, reconcile official "
            "status, score mission fit, and stage results without "
            "submission."
        ),
    )

    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help=(
            "Funding keyword. Repeat to supply multiple keywords."
        ),
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=20,
        help="Grants.gov rows per keyword (1-100).",
    )
    parser.add_argument(
        "--max-details",
        type=int,
        default=60,
        help="Maximum unique opportunities to fetch and score.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Number of ranked opportunities to print.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="JSON output path.",
    )
    parser.add_argument(
        "--no-authority-check",
        action="store_true",
        help="Skip official agency status-page reconciliation.",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    summary, results = run_live_sweep(
        keywords=args.keyword or None,
        rows_per_keyword=args.rows,
        max_details=args.max_details,
        verify_authority=not args.no_authority_check,
        output_path=Path(args.output).expanduser(),
    )

    print(
        json.dumps(
            {
                "summary": summary.to_dict(),
                "top_results": results[: max(0, args.top)],
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    print("SUBMISSION_PERFORMED=NO")
    print("HUMAN_REVIEW_REQUIRED=YES")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
