from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from grantbot.agents.crewai_multimodel import ROLE_ORDER, ai_policy, role_plan_status


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "adaptive_intelligence_v30.sqlite3"
DB_LOCK = threading.RLock()
TRUSTED_FACT_STATES = {"VERIFIED", "APPROVED"}
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'_-]*")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
NUMBER_RE = re.compile(r"(?<![A-Za-z])\$?\d[\d,]*(?:\.\d+)?%?")


@dataclass(frozen=True, slots=True)
class OpportunityValueResult:
    score: float
    expected_funding_value: float
    expected_value_per_hour: float
    pursuit_priority: str
    components: dict[str, float]
    blockers: list[str]
    rationale: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProvenanceSupport:
    sentence_index: int
    sentence: str
    support_status: str
    confidence: float
    supporting_fact_ids: list[str]
    supporting_sources: list[str]
    unsupported_numbers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ConsistencyIssue:
    severity: str
    code: str
    message: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _normalize_words(text: str) -> set[str]:
    return {
        token.lower()
        for token in WORD_RE.findall(text)
        if len(token) >= 3
    }


def _normalize_number(value: str) -> str:
    return value.replace("$", "").replace(",", "").strip()


def _connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def initialize_database(db_path: Path = DEFAULT_DB_PATH) -> None:
    with DB_LOCK, _connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS model_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                role TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                task_type TEXT NOT NULL,
                quality_score REAL,
                hallucination_rate REAL,
                latency_ms REAL,
                cost_usd REAL,
                success INTEGER NOT NULL,
                human_accepted INTEGER,
                metadata_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_model_runs_lookup
                ON model_runs(role, provider, model, task_type, created_at);

            CREATE TABLE IF NOT EXISTS funder_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                funder_key TEXT NOT NULL,
                funder_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                opportunity_id TEXT,
                outcome TEXT,
                amount_requested REAL,
                amount_awarded REAL,
                reviewer_score REAL,
                feedback TEXT NOT NULL,
                attributes_json TEXT NOT NULL,
                human_approved INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_funder_events_key
                ON funder_events(funder_key, created_at);

            CREATE TABLE IF NOT EXISTS approved_learning (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                artifact_key TEXT NOT NULL UNIQUE,
                section_type TEXT NOT NULL,
                funder_archetype TEXT NOT NULL,
                text TEXT NOT NULL,
                reviewer_score REAL,
                outcome TEXT,
                approved_by TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_approved_learning_lookup
                ON approved_learning(section_type, funder_archetype, created_at);
            """
        )
        connection.commit()


def record_model_run(
    *,
    role: str,
    provider: str,
    model: str,
    task_type: str,
    success: bool,
    quality_score: float | None = None,
    hallucination_rate: float | None = None,
    latency_ms: float | None = None,
    cost_usd: float | None = None,
    human_accepted: bool | None = None,
    metadata: Mapping[str, Any] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    if role not in ROLE_ORDER:
        raise ValueError(f"role must be one of {ROLE_ORDER}")
    if not provider.strip() or not model.strip() or not task_type.strip():
        raise ValueError("provider, model, and task_type are required")
    if quality_score is not None and not 0.0 <= quality_score <= 100.0:
        raise ValueError("quality_score must be between 0 and 100")
    if hallucination_rate is not None and not 0.0 <= hallucination_rate <= 1.0:
        raise ValueError("hallucination_rate must be between 0 and 1")
    if latency_ms is not None and latency_ms < 0:
        raise ValueError("latency_ms cannot be negative")
    if cost_usd is not None and cost_usd < 0:
        raise ValueError("cost_usd cannot be negative")

    initialize_database(db_path)
    with DB_LOCK, _connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO model_runs (
                created_at, role, provider, model, task_type, quality_score,
                hallucination_rate, latency_ms, cost_usd, success,
                human_accepted, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                role,
                provider.strip(),
                model.strip(),
                task_type.strip(),
                quality_score,
                hallucination_rate,
                latency_ms,
                cost_usd,
                1 if success else 0,
                None if human_accepted is None else (1 if human_accepted else 0),
                json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True, default=str),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def model_performance(
    *,
    role: str | None = None,
    task_type: str | None = None,
    min_samples: int = 1,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    if role is not None and role not in ROLE_ORDER:
        raise ValueError(f"role must be one of {ROLE_ORDER}")
    if min_samples < 1:
        raise ValueError("min_samples must be at least 1")

    initialize_database(db_path)
    clauses: list[str] = []
    parameters: list[Any] = []
    if role is not None:
        clauses.append("role = ?")
        parameters.append(role)
    if task_type is not None:
        clauses.append("task_type = ?")
        parameters.append(task_type)
    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""

    with DB_LOCK, _connect(db_path) as connection:
        rows = connection.execute(
            f"SELECT * FROM model_runs{where_sql} ORDER BY created_at DESC",
            parameters,
        ).fetchall()

    grouped: dict[tuple[str, str, str, str], list[sqlite3.Row]] = {}
    for row in rows:
        key = (row["role"], row["provider"], row["model"], row["task_type"])
        grouped.setdefault(key, []).append(row)

    results: list[dict[str, Any]] = []
    for (group_role, provider, model, group_task), items in grouped.items():
        if len(items) < min_samples:
            continue
        qualities = [float(item["quality_score"]) for item in items if item["quality_score"] is not None]
        hallucinations = [float(item["hallucination_rate"]) for item in items if item["hallucination_rate"] is not None]
        latencies = [float(item["latency_ms"]) for item in items if item["latency_ms"] is not None]
        costs = [float(item["cost_usd"]) for item in items if item["cost_usd"] is not None]
        human_votes = [int(item["human_accepted"]) for item in items if item["human_accepted"] is not None]
        success_rate = sum(int(item["success"]) for item in items) / len(items)
        quality = statistics.fmean(qualities) if qualities else 50.0
        hallucination = statistics.fmean(hallucinations) if hallucinations else 0.10
        human_acceptance = statistics.fmean(human_votes) if human_votes else success_rate
        latency = statistics.fmean(latencies) if latencies else 0.0
        cost = statistics.fmean(costs) if costs else 0.0

        reliability_component = success_rate * 30.0
        quality_component = _clamp(quality) * 0.40
        acceptance_component = human_acceptance * 20.0
        hallucination_component = (1.0 - _clamp(hallucination, 0.0, 1.0)) * 10.0
        performance_score = _clamp(
            reliability_component + quality_component + acceptance_component + hallucination_component
        )

        results.append(
            {
                "role": group_role,
                "provider": provider,
                "model": model,
                "task_type": group_task,
                "samples": len(items),
                "success_rate": round(success_rate, 4),
                "quality_score": round(quality, 2),
                "hallucination_rate": round(hallucination, 4),
                "human_acceptance_rate": round(human_acceptance, 4),
                "mean_latency_ms": round(latency, 2),
                "mean_cost_usd": round(cost, 6),
                "performance_score": round(performance_score, 2),
            }
        )

    return sorted(
        results,
        key=lambda item: (
            -float(item["performance_score"]),
            float(item["mean_cost_usd"]),
            float(item["mean_latency_ms"]),
        ),
    )


def score_opportunity(
    *,
    award_amount: float,
    win_probability: float,
    estimated_hours: float,
    strategic_fit: float,
    eligibility_confidence: float,
    award_value_score: float,
    application_effort_score: float,
    deadline_feasibility: float,
    organizational_readiness: float,
    hard_blockers: Sequence[str] | None = None,
) -> OpportunityValueResult:
    if award_amount < 0:
        raise ValueError("award_amount cannot be negative")
    if not 0.0 <= win_probability <= 1.0:
        raise ValueError("win_probability must be between 0 and 1")
    if estimated_hours <= 0:
        raise ValueError("estimated_hours must be greater than zero")

    components = {
        "strategic_fit": _clamp(strategic_fit),
        "eligibility_confidence": _clamp(eligibility_confidence),
        "award_value": _clamp(award_value_score),
        "win_probability": _clamp(win_probability * 100.0),
        "application_effort": _clamp(application_effort_score),
        "deadline_feasibility": _clamp(deadline_feasibility),
        "organizational_readiness": _clamp(organizational_readiness),
    }
    weights = {
        "strategic_fit": 0.25,
        "eligibility_confidence": 0.25,
        "award_value": 0.10,
        "win_probability": 0.15,
        "application_effort": 0.10,
        "deadline_feasibility": 0.10,
        "organizational_readiness": 0.05,
    }
    score = sum(components[key] * weights[key] for key in weights)
    blockers = [item.strip() for item in hard_blockers or [] if item.strip()]
    if blockers:
        score = min(score, 24.99)

    expected_value = award_amount * win_probability
    value_per_hour = expected_value / estimated_hours

    if blockers:
        priority = "HOLD"
    elif score >= 85.0:
        priority = "PRIORITIZE"
    elif score >= 70.0:
        priority = "APPLY"
    elif score >= 55.0:
        priority = "CONSIDER"
    elif score >= 40.0:
        priority = "MONITOR"
    else:
        priority = "REJECT"

    rationale = [
        f"Weighted pursuit score is {score:.2f}/100.",
        f"Expected funding value is ${expected_value:,.2f} at a {win_probability * 100.0:.1f}% win estimate.",
        f"Expected value per estimated application hour is ${value_per_hour:,.2f}.",
    ]
    if blockers:
        rationale.append("Hard blockers force HOLD regardless of mission fit or expected value.")
    elif components["eligibility_confidence"] < 70.0:
        rationale.append("Eligibility confidence is below 70 and should be resolved before substantial drafting effort.")
    elif value_per_hour > 0:
        rationale.append("Portfolio ranking should compare this value-per-hour figure against other eligible opportunities.")

    return OpportunityValueResult(
        score=round(score, 2),
        expected_funding_value=round(expected_value, 2),
        expected_value_per_hour=round(value_per_hour, 2),
        pursuit_priority=priority,
        components={key: round(value, 2) for key, value in components.items()},
        blockers=blockers,
        rationale=rationale,
    )


def record_funder_event(
    *,
    funder_key: str,
    funder_name: str,
    event_type: str,
    human_approved: bool,
    opportunity_id: str | None = None,
    outcome: str | None = None,
    amount_requested: float | None = None,
    amount_awarded: float | None = None,
    reviewer_score: float | None = None,
    feedback: str = "",
    attributes: Mapping[str, Any] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    if not funder_key.strip() or not funder_name.strip() or not event_type.strip():
        raise ValueError("funder_key, funder_name, and event_type are required")
    for name, value in (("amount_requested", amount_requested), ("amount_awarded", amount_awarded)):
        if value is not None and value < 0:
            raise ValueError(f"{name} cannot be negative")
    if reviewer_score is not None and not 0.0 <= reviewer_score <= 100.0:
        raise ValueError("reviewer_score must be between 0 and 100")

    initialize_database(db_path)
    with DB_LOCK, _connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO funder_events (
                created_at, funder_key, funder_name, event_type, opportunity_id,
                outcome, amount_requested, amount_awarded, reviewer_score,
                feedback, attributes_json, human_approved
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                funder_key.strip().lower(),
                funder_name.strip(),
                event_type.strip().upper(),
                opportunity_id.strip() if opportunity_id else None,
                outcome.strip().upper() if outcome else None,
                amount_requested,
                amount_awarded,
                reviewer_score,
                feedback.strip(),
                json.dumps(dict(attributes or {}), ensure_ascii=False, sort_keys=True, default=str),
                1 if human_approved else 0,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def funder_profile(
    funder_key: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    key = funder_key.strip().lower()
    if not key:
        raise ValueError("funder_key is required")
    initialize_database(db_path)
    with DB_LOCK, _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM funder_events WHERE funder_key = ? ORDER BY created_at ASC",
            (key,),
        ).fetchall()

    if not rows:
        return {
            "funder_key": key,
            "known": False,
            "events": 0,
            "approved_events": 0,
            "applications": 0,
            "wins": 0,
            "win_rate": None,
            "requested_total": 0.0,
            "awarded_total": 0.0,
            "mean_reviewer_score": None,
            "feedback": [],
            "attributes": {},
        }

    approved = [row for row in rows if int(row["human_approved"]) == 1]
    application_rows = [row for row in approved if row["event_type"] in {"APPLICATION", "OUTCOME"}]
    outcome_rows = [row for row in approved if row["outcome"]]
    wins = [row for row in outcome_rows if str(row["outcome"]).upper() in {"AWARDED", "FUNDED", "WON"}]
    reviewer_scores = [float(row["reviewer_score"]) for row in approved if row["reviewer_score"] is not None]
    requested_total = sum(float(row["amount_requested"] or 0.0) for row in approved)
    awarded_total = sum(float(row["amount_awarded"] or 0.0) for row in approved)

    attributes: dict[str, Any] = {}
    feedback: list[str] = []
    for row in approved:
        try:
            payload = json.loads(row["attributes_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            attributes.update(payload)
        text = str(row["feedback"] or "").strip()
        if text and text not in feedback:
            feedback.append(text)

    return {
        "funder_key": key,
        "funder_name": rows[-1]["funder_name"],
        "known": True,
        "events": len(rows),
        "approved_events": len(approved),
        "applications": len(application_rows),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(outcome_rows), 4) if outcome_rows else None,
        "requested_total": round(requested_total, 2),
        "awarded_total": round(awarded_total, 2),
        "mean_reviewer_score": round(statistics.fmean(reviewer_scores), 2) if reviewer_scores else None,
        "feedback": feedback,
        "attributes": attributes,
    }


def save_approved_learning(
    *,
    artifact_key: str,
    section_type: str,
    funder_archetype: str,
    text: str,
    approved_by: str,
    reviewer_score: float | None = None,
    outcome: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    human_approved: bool,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    if not human_approved:
        raise PermissionError("Learning artifacts require explicit human approval")
    if not artifact_key.strip() or not section_type.strip() or not funder_archetype.strip():
        raise ValueError("artifact_key, section_type, and funder_archetype are required")
    if not text.strip() or not approved_by.strip():
        raise ValueError("text and approved_by are required")
    if reviewer_score is not None and not 0.0 <= reviewer_score <= 100.0:
        raise ValueError("reviewer_score must be between 0 and 100")

    initialize_database(db_path)
    with DB_LOCK, _connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO approved_learning (
                created_at, artifact_key, section_type, funder_archetype,
                text, reviewer_score, outcome, approved_by, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(artifact_key) DO UPDATE SET
                created_at=excluded.created_at,
                section_type=excluded.section_type,
                funder_archetype=excluded.funder_archetype,
                text=excluded.text,
                reviewer_score=excluded.reviewer_score,
                outcome=excluded.outcome,
                approved_by=excluded.approved_by,
                metadata_json=excluded.metadata_json
            """,
            (
                _utc_now(),
                artifact_key.strip(),
                section_type.strip(),
                funder_archetype.strip(),
                text.strip(),
                reviewer_score,
                outcome.strip().upper() if outcome else None,
                approved_by.strip(),
                json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True, default=str),
            ),
        )
        connection.commit()
        if cursor.lastrowid:
            return int(cursor.lastrowid)
        row = connection.execute(
            "SELECT id FROM approved_learning WHERE artifact_key = ?",
            (artifact_key.strip(),),
        ).fetchone()
        if row is None:
            raise RuntimeError("Approved learning record could not be persisted")
        return int(row["id"])


def sentence_provenance(
    *,
    text: str,
    facts: Sequence[Mapping[str, Any]],
    minimum_overlap: float = 0.28,
) -> list[ProvenanceSupport]:
    if not text.strip():
        raise ValueError("text cannot be empty")
    if not 0.0 < minimum_overlap <= 1.0:
        raise ValueError("minimum_overlap must be greater than 0 and at most 1")

    trusted: list[dict[str, Any]] = []
    for raw in facts:
        state = str(raw.get("verification_state", raw.get("status", ""))).strip().upper()
        if state not in TRUSTED_FACT_STATES:
            continue
        value = raw.get("value", raw.get("answer"))
        if value in (None, "", [], {}):
            continue
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        words = _normalize_words(rendered)
        if not words:
            continue
        trusted.append(
            {
                "id": str(raw.get("fact_id", raw.get("id", raw.get("fact_key", "unknown")))),
                "source": str(raw.get("source", "")).strip(),
                "words": words,
                "numbers": {_normalize_number(item) for item in NUMBER_RE.findall(rendered)},
            }
        )

    sentences = [part.strip() for part in SENTENCE_RE.split(text.strip()) if part.strip()]
    results: list[ProvenanceSupport] = []
    for index, sentence in enumerate(sentences, start=1):
        sentence_words = _normalize_words(sentence)
        sentence_numbers = {_normalize_number(item) for item in NUMBER_RE.findall(sentence)}
        matches: list[tuple[float, dict[str, Any]]] = []
        for fact in trusted:
            overlap_count = len(sentence_words & fact["words"])
            denominator = max(1, min(len(sentence_words), len(fact["words"])))
            overlap = overlap_count / denominator
            number_match = bool(sentence_numbers) and sentence_numbers.issubset(fact["numbers"])
            if overlap >= minimum_overlap or number_match:
                score = min(1.0, overlap + (0.25 if number_match else 0.0))
                matches.append((score, fact))

        matches.sort(key=lambda item: item[0], reverse=True)
        selected = matches[:5]
        supported_numbers: set[str] = set()
        for _, fact in selected:
            supported_numbers.update(fact["numbers"])
        unsupported_numbers = sorted(sentence_numbers - supported_numbers)

        if selected and not unsupported_numbers:
            status = "SUPPORTED"
            confidence = max(score for score, _ in selected)
        elif selected:
            status = "PARTIAL"
            confidence = max(score for score, _ in selected) * 0.75
        elif sentence_numbers:
            status = "UNSUPPORTED"
            confidence = 0.0
        else:
            status = "UNRESOLVED"
            confidence = 0.0

        results.append(
            ProvenanceSupport(
                sentence_index=index,
                sentence=sentence,
                support_status=status,
                confidence=round(confidence, 4),
                supporting_fact_ids=[fact["id"] for _, fact in selected],
                supporting_sources=list(dict.fromkeys(fact["source"] for _, fact in selected if fact["source"])),
                unsupported_numbers=unsupported_numbers,
            )
        )
    return results


def consistency_audit(
    *,
    narrative: str,
    budget: Mapping[str, float],
    workplan: Mapping[str, Any],
    expected_total: float | None = None,
    tolerance: float = 0.01,
) -> list[ConsistencyIssue]:
    if tolerance < 0:
        raise ValueError("tolerance cannot be negative")
    numeric_budget: dict[str, float] = {}
    for key, value in budget.items():
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError(f"budget value for {key!r} must be a finite non-negative number")
        numeric_budget[str(key)] = numeric

    issues: list[ConsistencyIssue] = []
    calculated_total = sum(numeric_budget.values())
    if expected_total is not None and abs(calculated_total - float(expected_total)) > tolerance:
        issues.append(
            ConsistencyIssue(
                severity="BLOCKER",
                code="BUDGET_TOTAL_MISMATCH",
                message="Budget line items do not equal the expected total.",
                evidence={"calculated_total": calculated_total, "expected_total": float(expected_total)},
            )
        )

    narrative_numbers = {_normalize_number(item) for item in NUMBER_RE.findall(narrative)}
    structured_numbers: set[str] = set()
    for value in numeric_budget.values():
        structured_numbers.add(str(int(value)) if value.is_integer() else str(value))
    for value in workplan.values():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
            structured_numbers.add(str(int(numeric)) if numeric.is_integer() else str(numeric))
        elif isinstance(value, str):
            structured_numbers.update(_normalize_number(item) for item in NUMBER_RE.findall(value))

    unsupported_numeric_claims = sorted(
        number for number in narrative_numbers
        if number not in structured_numbers and not number.endswith("%")
    )
    if unsupported_numeric_claims:
        issues.append(
            ConsistencyIssue(
                severity="WARNING",
                code="NARRATIVE_NUMBERS_NOT_STRUCTURED",
                message="Narrative contains numeric claims that are not present in the budget or workplan inputs.",
                evidence={"numbers": unsupported_numeric_claims},
            )
        )

    lower_narrative = narrative.lower()
    for key, value in numeric_budget.items():
        normalized_key = key.replace("_", " ").strip().lower()
        if value > 0 and normalized_key and normalized_key not in lower_narrative:
            issues.append(
                ConsistencyIssue(
                    severity="INFO",
                    code="BUDGET_CATEGORY_NOT_MENTIONED",
                    message=f"Funded budget category {key!r} is not explicitly referenced in the narrative.",
                    evidence={"category": key, "amount": value},
                )
            )

    for key, value in workplan.items():
        if isinstance(value, str) and value.strip():
            words = _normalize_words(value)
            if len(words) >= 2 and not any(word in lower_narrative for word in words):
                issues.append(
                    ConsistencyIssue(
                        severity="INFO",
                        code="WORKPLAN_ELEMENT_NOT_REFLECTED",
                        message=f"Workplan element {key!r} has no obvious narrative counterpart.",
                        evidence={"workplan_key": key, "workplan_value": value},
                    )
                )

    return issues


def intelligence_status(*, db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    initialize_database(db_path)
    performance = model_performance(db_path=db_path)
    with DB_LOCK, _connect(db_path) as connection:
        model_runs = int(connection.execute("SELECT COUNT(*) AS count FROM model_runs").fetchone()["count"])
        funder_events = int(connection.execute("SELECT COUNT(*) AS count FROM funder_events").fetchone()["count"])
        learning_records = int(connection.execute("SELECT COUNT(*) AS count FROM approved_learning").fetchone()["count"])
    return {
        "version": "30.0.0",
        "ai_policy": ai_policy(),
        "role_plan": role_plan_status(),
        "telemetry": {
            "model_runs": model_runs,
            "ranked_models": performance,
        },
        "funder_memory_events": funder_events,
        "human_approved_learning_records": learning_records,
        "truth_model": "canonical facts + explicit provenance + deterministic gates",
        "local_ai_required": False,
        "human_review_required": True,
        "external_submission_enabled": False,
        "safe_to_submit": False,
    }
