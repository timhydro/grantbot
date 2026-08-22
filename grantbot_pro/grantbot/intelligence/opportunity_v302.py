from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "opportunity_intelligence_v302.sqlite3"
DB_LOCK = threading.RLock()
WORD_RE = re.compile(r"[a-z][a-z0-9'-]{2,}")

NONPROFIT_SIGNALS = (
    "nonprofit",
    "non-profit",
    "501(c)(3)",
    "501c3",
    "faith-based",
    "community-based organization",
)
GOVERNMENT_SIGNALS = (
    "state government",
    "county government",
    "city or township government",
    "special district government",
    "unit of local government",
    "tribal government",
    "public housing authorit",
)
ACADEMIC_ELIGIBILITY_SIGNALS = (
    "institution of higher education",
    "institutions of higher education",
    "public and state controlled institutions",
    "private institution of higher education",
)
INDIVIDUAL_SIGNALS = ("individual applicants", "individuals only")

# These signals are intentionally title-weighted. A NOFO may mention research or
# education incidentally; GrantBot rejects only when the opportunity itself is an
# obviously incompatible research/academic instrument.
OUT_OF_SCOPE_TITLE_SIGNALS: dict[str, tuple[str, ...]] = {
    "clinical_or_biomedical_research": (
        "clinical trial",
        "clinical and translational science",
        "biomedical research",
        "small grant program for the ncats",
        "research project grant",
    ),
    "academic_fellowship": (
        "postdoctoral fellowship",
        "doctoral fellowship",
        "research fellowship",
        "faculty development",
    ),
    "scientific_infrastructure": (
        "advanced cyberinfrastructure",
        "research infrastructure",
        "scientific instrumentation",
    ),
    "foreign_assistance": (
        "u.s. mission to ",
        "embassy program",
        "international exchange program",
    ),
}

FEDERAL_SIGNALS = (
    "bureau of justice assistance",
    "department of",
    "national institutes of health",
    "grants.gov",
    "assistance listing",
    "notice of funding opportunity",
    "nofo",
)

LEARNING_DECISIONS = {"PURSUE", "PARTNER_ONLY", "HOLD", "REJECT"}


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    decision: str
    direct_applicant_allowed: bool
    partner_route_available: bool
    hard_blockers: list[str]
    warnings: list[str]
    negative_domains: list[str]
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _tokens(value: str) -> set[str]:
    return {token for token in WORD_RE.findall(value.casefold()) if len(token) >= 4}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def assess_eligibility(
    *,
    title: str,
    funder: str = "",
    description: str = "",
    eligibility: str = "",
    nofo_text: str = "",
) -> EligibilityDecision:
    title_lower = _clean(title).casefold()
    eligibility_lower = _clean(eligibility).casefold()
    material = " ".join(
        (_clean(title), _clean(funder), _clean(description), eligibility_lower, _clean(nofo_text))
    ).casefold()
    blockers: list[str] = []
    warnings: list[str] = []
    evidence: list[str] = []
    negative_domains: list[str] = []

    for domain, signals in OUT_OF_SCOPE_TITLE_SIGNALS.items():
        hits = [signal for signal in signals if signal in title_lower]
        if hits:
            negative_domains.append(domain)
            blockers.append(f"out-of-scope opportunity domain: {domain}")
            evidence.extend(f"title contains '{hit}'" for hit in hits)

    nonprofit_allowed = any(signal in eligibility_lower for signal in NONPROFIT_SIGNALS)
    government_present = any(signal in eligibility_lower for signal in GOVERNMENT_SIGNALS)
    academic_present = any(signal in eligibility_lower for signal in ACADEMIC_ELIGIBILITY_SIGNALS)
    individual_present = any(signal in eligibility_lower for signal in INDIVIDUAL_SIGNALS)

    if eligibility_lower:
        if nonprofit_allowed:
            evidence.append("eligibility explicitly includes a nonprofit or faith-based route")
        elif government_present:
            evidence.append("eligibility identifies government applicant types but no nonprofit route")
        elif academic_present:
            evidence.append("eligibility identifies higher-education applicants but no nonprofit route")
        elif individual_present:
            evidence.append("eligibility identifies individuals but no organizational route")
        else:
            warnings.append("applicant eligibility is present but does not explicitly confirm a nonprofit route")
    else:
        warnings.append("applicant eligibility has not been acquired")

    if blockers:
        decision = "REJECT"
        direct = False
        partner = False
    elif government_present and not nonprofit_allowed:
        decision = "PARTNER_ONLY"
        direct = False
        partner = True
        blockers.append("direct application blocked: opportunity appears limited to government applicants")
    elif (academic_present or individual_present) and not nonprofit_allowed:
        decision = "REJECT"
        direct = False
        partner = False
        blockers.append("direct application blocked: applicant type is incompatible")
    elif nonprofit_allowed:
        decision = "DIRECT"
        direct = True
        partner = True
    else:
        decision = "VERIFY"
        direct = False
        partner = True

    if "limited competition" in material and decision not in {"REJECT", "PARTNER_ONLY"}:
        warnings.append("limited competition requires confirmation of every applicant restriction")

    return EligibilityDecision(
        decision=decision,
        direct_applicant_allowed=direct,
        partner_route_available=partner,
        hard_blockers=list(dict.fromkeys(blockers)),
        warnings=list(dict.fromkeys(warnings)),
        negative_domains=list(dict.fromkeys(negative_domains)),
        evidence=list(dict.fromkeys(evidence)),
    )


def source_completeness(
    *,
    title: str,
    funder: str,
    source_url: str,
    eligibility: str,
    nofo_text: str,
    extracted_questions: Sequence[str],
    extracted_requirements: Sequence[str],
) -> dict[str, Any]:
    material = " ".join((title, funder, source_url, nofo_text)).casefold()
    federal = any(signal in material for signal in FEDERAL_SIGNALS)
    full_text = len(_clean(nofo_text)) >= 1000
    eligibility_present = bool(_clean(eligibility))
    requirements_present = bool(extracted_questions or extracted_requirements)
    missing: list[str] = []
    if not source_url.strip():
        missing.append("official source URL")
    if not eligibility_present:
        missing.append("applicant eligibility")
    if federal and not full_text:
        missing.append("full federal NOFO text")
    if federal and not requirements_present:
        missing.append("application requirements or questions")

    if federal and missing:
        readiness_cap = 25
    elif missing:
        readiness_cap = 60
    else:
        readiness_cap = 100
    return {
        "federal": federal,
        "full_announcement_present": full_text,
        "eligibility_present": eligibility_present,
        "requirements_present": requirements_present,
        "missing": missing,
        "readiness_cap": readiness_cap,
        "complete_for_drafting": not missing,
    }


def initialize_learning_database(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with DB_LOCK, sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS opportunity_adjudications_v302 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                opportunity_id TEXT NOT NULL,
                title TEXT NOT NULL,
                funder TEXT NOT NULL,
                decision TEXT NOT NULL,
                rationale TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                human_approved INTEGER NOT NULL,
                features_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_opportunity_adjudications_v302
                ON opportunity_adjudications_v302(funder, decision, created_at);
            """
        )


def record_opportunity_adjudication(
    *,
    opportunity_id: str,
    title: str,
    funder: str,
    decision: str,
    rationale: str,
    reviewer: str,
    human_approved: bool,
    features: Mapping[str, Any] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    normalized = _clean(decision).upper()
    if normalized not in LEARNING_DECISIONS:
        raise ValueError(f"decision must be one of {sorted(LEARNING_DECISIONS)}")
    if not human_approved:
        raise PermissionError("opportunity learning requires explicit human approval")
    if not _clean(rationale) or not _clean(reviewer):
        raise ValueError("rationale and reviewer are required")
    initialize_learning_database(db_path)
    with DB_LOCK, sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO opportunity_adjudications_v302(
                created_at, opportunity_id, title, funder, decision,
                rationale, reviewer, human_approved, features_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                _utc_now(),
                _clean(opportunity_id),
                _clean(title),
                _clean(funder),
                normalized,
                _clean(rationale),
                _clean(reviewer),
                json.dumps(dict(features or {}), ensure_ascii=False, sort_keys=True, default=str),
            ),
        )
        return int(cursor.lastrowid)


def learned_opportunity_signal(
    *,
    title: str,
    funder: str,
    db_path: Path = DEFAULT_DB_PATH,
    minimum_similarity: float = 0.25,
) -> dict[str, Any]:
    initialize_learning_database(db_path)
    with DB_LOCK, sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM opportunity_adjudications_v302
            WHERE human_approved=1 ORDER BY created_at DESC LIMIT 500
            """
        ).fetchall()
    target = _tokens(title)
    target_funder = _clean(funder).casefold()
    weights = {"PURSUE": 1.0, "PARTNER_ONLY": 0.2, "HOLD": -0.35, "REJECT": -1.0}
    matches: list[dict[str, Any]] = []
    weighted_total = 0.0
    similarity_total = 0.0
    for row in rows:
        candidate = _tokens(str(row["title"]))
        similarity = len(target & candidate) / len(target | candidate) if target and candidate else 0.0
        if target_funder and target_funder == _clean(row["funder"]).casefold():
            similarity = min(1.0, similarity + 0.25)
        if similarity < minimum_similarity:
            continue
        decision = str(row["decision"])
        weighted_total += weights[decision] * similarity
        similarity_total += similarity
        matches.append(
            {
                "opportunity_id": row["opportunity_id"],
                "decision": decision,
                "similarity": round(similarity, 4),
                "rationale": row["rationale"],
            }
        )
    normalized = weighted_total / similarity_total if similarity_total else 0.0
    # Human history may move a soft fit score by at most ten points. It can never
    # alter authoritative eligibility, deadline, or evidence decisions.
    adjustment = round(max(-10.0, min(10.0, normalized * 10.0)), 2)
    return {
        "sample_count": len(matches),
        "score_adjustment": adjustment,
        "matches": sorted(matches, key=lambda item: item["similarity"], reverse=True)[:10],
        "policy": "human-approved history adjusts soft ranking only; hard gates remain authoritative",
    }
