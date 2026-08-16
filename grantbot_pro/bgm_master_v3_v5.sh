#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/grantbot_pro"
cd "$ROOT"

if [[ ! -f grantbot/app.py ]]; then
  echo "ERROR: $ROOT/grantbot/app.py not found" >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "ERROR: $ROOT/.venv not found" >&2
  exit 1
fi

source .venv/bin/activate

STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p backups grantbot/writing grantbot/nofo grantbot/automation grantbot/api tests logs
cp grantbot/app.py "backups/app_before_master_v3_v5_${STAMP}.py"

touch grantbot/writing/__init__.py
touch grantbot/nofo/__init__.py
touch grantbot/automation/__init__.py
touch grantbot/api/__init__.py

cat > grantbot/writing/ollama_provider.py <<'PY'
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    base_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip()
    timeout_seconds: int = 300


class OllamaProvider:
    def __init__(self, config: OllamaConfig | None = None) -> None:
        self.config = config or OllamaConfig()
        if not self.config.model:
            raise RuntimeError("OLLAMA_MODEL cannot be empty")

    def health(self) -> dict[str, Any]:
        req = Request(f"{self.config.base_url}/api/tags", method="GET")
        try:
            with urlopen(req, timeout=10) as response:
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError) as exc:
            return {"available": False, "model": self.config.model, "error": str(exc)}
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {}
        names = {
            str(item.get("name", ""))
            for item in body.get("models", [])
            if isinstance(item, dict)
        }
        return {
            "available": True,
            "model": self.config.model,
            "model_installed": self.config.model in names,
        }

    def generate(
        self,
        prompt: str,
        *,
        system: str,
        temperature: float = 0.3,
    ) -> str:
        if not prompt.strip():
            raise ValueError("prompt cannot be empty")
        if not system.strip():
            raise ValueError("system cannot be empty")
        if not 0.0 <= temperature <= 1.0:
            raise ValueError("temperature must be between 0 and 1")

        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature},
        }
        req = Request(
            f"{self.config.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Ollama unavailable: {exc.reason}") from exc

        body = json.loads(raw)
        text = body.get("response")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Ollama returned empty response")
        return text.strip()
PY

cat > grantbot/writing/quality_gate.py <<'PY'
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


NUMBER_RE = re.compile(r"(?<!\w)\$?\d[\d,]*(?:\.\d+)?%?(?!\w)")


@dataclass(frozen=True, slots=True)
class QualityResult:
    passed: bool
    score: int
    word_count: int
    issues: list[str]
    unsupported_numbers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_draft(
    *,
    question: str,
    draft: str,
    facts: list[dict[str, Any]],
    max_words: int | None = None,
    required_terms: list[str] | None = None,
) -> QualityResult:
    text = draft.strip()
    if not text:
        return QualityResult(False, 0, 0, ["Draft is empty"], [])

    source = " ".join(
        str(f.get("value", f.get("answer", "")))
        for f in facts
        if f.get("value", f.get("answer")) not in (None, "", [], {})
    ).lower()

    unsupported = sorted(
        {
            n
            for n in NUMBER_RE.findall(text)
            if n.lower() not in source
        }
    )

    score = 100
    issues: list[str] = []
    wc = len(text.split())

    if unsupported:
        score -= min(45, 15 * len(unsupported))
        issues.append("Unsupported numeric claims: " + ", ".join(unsupported))

    if max_words is not None and wc > max_words:
        score -= 25
        issues.append(f"Word limit exceeded: {wc}/{max_words}")

    missing_terms = [
        t
        for t in (required_terms or [])
        if t.strip() and t.lower() not in text.lower()
    ]
    if missing_terms:
        score -= min(25, 5 * len(missing_terms))
        issues.append("Missing funder priorities: " + ", ".join(missing_terms))

    if not any(
        token in text.lower()
        for token in re.findall(r"[a-zA-Z]{4,}", question.lower())
    ):
        score -= 15
        issues.append("Draft may not directly answer the question")

    score = max(0, min(100, score))
    return QualityResult(
        passed=score >= 80 and not unsupported,
        score=score,
        word_count=wc,
        issues=issues,
        unsupported_numbers=unsupported,
    )
PY

cat > grantbot/writing/master_writer.py <<'PY'
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from grantbot.writing.ollama_provider import OllamaProvider
from grantbot.writing.quality_gate import evaluate_draft


TRUSTED = {"VERIFIED", "APPROVED"}
PLANNING = {"DRAFT"}

SECTION_STRATEGIES = {
    "executive_summary": "Lead with mission fit, problem, intervention, credibility, and investment case.",
    "statement_of_need": "Define the problem precisely using only supplied evidence.",
    "program_design": "Explain who does what, for whom, how, where, and in what sequence.",
    "goals_objectives": "Use measurable language only where targets are supplied.",
    "outcomes_evaluation": "Separate outputs, outcomes, and evaluation; never convert proposed outcomes into demonstrated results.",
    "organizational_capacity": "Use only verified leadership, experience, partnerships, systems, and governance.",
    "sustainability": "Describe realistic continuation mechanisms without inventing future funding.",
    "budget_narrative": "Connect verified costs to delivery; never invent line items or amounts.",
    "partnerships": "Describe only verified or approved partners and roles.",
    "general": "Answer the exact question directly using the strongest relevant facts.",
}


@dataclass(frozen=True, slots=True)
class WriterResult:
    status: str
    section: str
    question: str
    draft: str | None
    facts_used: list[dict[str, Any]]
    planning_context: list[dict[str, Any]]
    missing_information: list[dict[str, Any]]
    quality: dict[str, Any] | None
    provider: str
    model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(raw.get("id", "")).strip(),
        "category": str(raw.get("category", "general")).strip().lower(),
        "key": str(raw.get("key", "")).strip(),
        "value": raw.get("value", raw.get("answer")),
        "status": str(raw.get("status", "APPROVED")).strip().upper(),
        "source": str(raw.get("source", "unknown")).strip(),
        "notes": str(raw.get("notes", "")).strip(),
    }


def _partition(facts: list[dict[str, Any]]):
    trusted, planning, missing = [], [], []
    for raw in facts:
        fact = _normalize(raw)
        if fact["status"] in TRUSTED and fact["value"] not in (None, "", [], {}):
            trusted.append(fact)
        elif fact["status"] in PLANNING and fact["value"] not in (None, "", [], {}):
            planning.append(fact)
        elif fact["status"] == "MISSING":
            missing.append(fact)
    return trusted, planning, missing


def _block(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return "(none)"
    return "\n".join(
        f"- [{f['status']}] {f['category']}.{f['key']}: {f['value']} (source: {f['source']})"
        for f in facts
    )


def _system() -> str:
    return """
You are the senior grant strategist for BrokenGrowthMinistries with doctoral-level mastery of nonprofit grant strategy, housing/reentry programs, workforce development, evaluation, and persuasive professional writing.

Write the strongest truthful, funder-aligned response supported by the record.

Use ethos through credibility, pathos through dignified human stakes, and logos through implementation logic and responsible resource use. Frame funding as a high-value community investment when facts support that framing. Use precise, vivid language without exaggeration.

VERIFIED and APPROVED facts may be stated as facts.
DRAFT facts are planning context only and must remain prospective.
MISSING facts must never be guessed, estimated, rounded, or fabricated.
Never invent statistics, budgets, outcomes, partnerships, beneficiary counts, housing units, wages, dates, certifications, or success rates.
Return only the final grant narrative.
""".strip()


def write_answer(
    *,
    question: str,
    section: str,
    facts: list[dict[str, Any]],
    grant_title: str = "",
    funder: str = "",
    priorities: list[str] | None = None,
    requirements: list[str] | None = None,
    max_words: int | None = None,
    provider: OllamaProvider | None = None,
) -> WriterResult:
    if not question.strip():
        raise ValueError("question cannot be empty")

    section = section.strip().lower() or "general"
    if section not in SECTION_STRATEGIES:
        section = "general"

    trusted, planning, missing = _partition(facts)
    active = provider or OllamaProvider()

    if not trusted and not planning:
        return WriterResult(
            "MISSING_INFORMATION",
            section,
            question,
            None,
            [],
            [],
            missing,
            None,
            "ollama",
            active.config.model,
        )

    priorities = [p.strip() for p in (priorities or []) if p.strip()]
    requirements = [r.strip() for r in (requirements or []) if r.strip()]

    prompt = f"""
GRANT: {grant_title or "(not supplied)"}
FUNDER: {funder or "(not supplied)"}
SECTION: {section}
STRATEGY: {SECTION_STRATEGIES[section]}
QUESTION: {question}

FUNDER PRIORITIES:
{chr(10).join("- " + p for p in priorities) or "(none)"}

REQUIREMENTS:
{chr(10).join("- " + r for r in requirements) or "(none)"}

TRUSTED FACTS:
{_block(trusted)}

PLANNING CONTEXT:
{_block(planning)}

KNOWN MISSING:
{_block(missing)}

MAX WORDS: {max_words if max_words is not None else "not specified"}

Write only the final submission-quality narrative.
""".strip()

    draft = active.generate(prompt, system=_system(), temperature=0.3)
    quality = evaluate_draft(
        question=question,
        draft=draft,
        facts=trusted + planning,
        max_words=max_words,
        required_terms=priorities,
    )

    return WriterResult(
        "READY_FOR_HUMAN_REVIEW" if quality.passed else "REVISION_REQUIRED",
        section,
        question,
        draft,
        trusted,
        planning,
        missing,
        quality.to_dict(),
        "ollama",
        active.config.model,
    )
PY

cat > grantbot/nofo/analyzer.py <<'PY'
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


DOMAIN_WEIGHTS = {
    "reentry": 20,
    "homelessness": 20,
    "housing": 20,
    "employment": 15,
    "workforce": 15,
    "supportive_services": 10,
}

DOMAIN_TERMS = {
    "reentry": ("reentry", "re-entry", "formerly incarcerated", "justice-involved"),
    "homelessness": ("homelessness", "homeless", "unsheltered"),
    "housing": ("housing", "supportive housing", "transitional housing", "affordable housing"),
    "employment": ("employment", "job placement", "economic opportunity"),
    "workforce": ("workforce", "job training", "skills training", "vocational"),
    "supportive_services": ("supportive services", "case management", "mentoring", "life skills", "transportation"),
}

HARD_REJECT = (
    "postdoctoral applicants only",
    "institutions of higher education only",
    "tribal governments only",
    "state governments only",
    "county governments only",
    "city governments only",
    "individual applicants only",
    "for-profit organizations only",
)


@dataclass(frozen=True, slots=True)
class NofoAnalysis:
    fit_score: int
    priority: str
    hard_reject: bool
    blockers: list[str]
    matched_domains: dict[str, int]
    application_questions: list[str]
    priorities: list[str]
    requirements: list[str]
    writer_handoff: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_nofo(
    text: str,
    *,
    title: str = "",
    funder: str = "",
    opportunity_number: str = "",
    organization_missing: list[str] | None = None,
) -> NofoAnalysis:
    if len(text.strip()) < 20:
        raise ValueError("NOFO text is too short")

    lower = text.lower()
    blockers = [f"hard eligibility conflict: {term}" for term in HARD_REJECT if term in lower]
    hard = bool(blockers)

    matched: dict[str, int] = {}
    score = 0
    for domain, weight in DOMAIN_WEIGHTS.items():
        if any(term in lower for term in DOMAIN_TERMS[domain]):
            matched[domain] = weight
            score += weight

    if "florida" in lower or "pensacola" in lower or "escambia" in lower:
        score += 5

    if any(term in lower for term in ("nonprofit", "non-profit", "501(c)(3)", "faith-based")):
        score += 5

    score = 0 if hard else min(100, score)

    if hard:
        priority = "REJECT"
    elif score >= 80:
        priority = "HIGH"
    elif score >= 60:
        priority = "MEDIUM"
    elif score >= 40:
        priority = "LOW"
    else:
        priority = "VERY_LOW"

    questions = []
    for line in text.splitlines():
        line = " ".join(line.strip().split())
        if line.endswith("?") and len(line) >= 12:
            q = re.sub(r"^\s*(?:\d+[.)]|[A-Z][.)])\s*", "", line)
            if q not in questions:
                questions.append(q)

    priorities = []
    for domain, terms in DOMAIN_TERMS.items():
        if any(term in lower for term in terms):
            priorities.append(domain.replace("_", " "))

    requirements = []
    for line in text.splitlines():
        stripped = " ".join(line.split())
        low = stripped.lower()
        if any(x in low for x in ("must submit", "must include", "is required", "are required", "shall ")):
            if stripped and stripped not in requirements:
                requirements.append(stripped)

    handoff = {
        "grant_title": title,
        "funder": funder,
        "opportunity_number": opportunity_number,
        "priorities": priorities,
        "requirements": requirements,
        "questions": questions,
        "fit_score": score,
        "priority": priority,
        "organization_missing": organization_missing or [],
    }

    return NofoAnalysis(
        score,
        priority,
        hard,
        blockers,
        matched,
        questions,
        priorities,
        requirements,
        handoff,
    )
PY

cat > grantbot/automation/opportunity_pipeline.py <<'PY'
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from grantbot.nofo.analyzer import analyze_nofo
from grantbot.writing.master_writer import write_answer
from grantbot.writing.ollama_provider import OllamaProvider


@dataclass(frozen=True, slots=True)
class Opportunity:
    id: str
    title: str
    funder: str = ""
    description: str = ""
    eligibility: str = ""
    deadline: str | None = None
    amount: float | None = None
    source_url: str = ""
    nofo_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _load_facts() -> list[dict[str, Any]]:
    try:
        from grantbot.knowledge.fact_registry import FactRegistry
    except ImportError:
        return []

    registry = FactRegistry()
    facts = []
    for f in registry.all():
        item = f.to_dict() if hasattr(f, "to_dict") else dict(f)
        facts.append(item)
    return facts


def _relevant(question: str, facts: list[dict[str, Any]], limit: int = 12):
    words = {
        w
        for w in re_clean(question)
        if len(w) >= 4
    }
    scored = []
    for fact in facts:
        status = str(fact.get("status", "")).upper()
        if status not in {"VERIFIED", "APPROVED", "DRAFT"}:
            continue
        searchable = " ".join(
            (
                str(fact.get("category", "")),
                str(fact.get("key", "")),
                str(fact.get("value", "")),
            )
        ).lower()
        score = sum(1 for w in words if w in searchable)
        if score:
            scored.append((score, fact))
    scored.sort(key=lambda x: -x[0])
    return [fact for _, fact in scored[:limit]]


def re_clean(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return cleaned.split()


def analyze_opportunity(
    opportunity: Opportunity,
    *,
    generate_drafts: bool = False,
) -> dict[str, Any]:
    text = " ".join(
        (
            opportunity.title,
            opportunity.description,
            opportunity.eligibility,
            opportunity.nofo_text,
        )
    )

    nofo = analyze_nofo(
        text,
        title=opportunity.title,
        funder=opportunity.funder,
    )

    blockers = list(nofo.blockers)

    if opportunity.deadline:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y"):
            try:
                d = datetime.strptime(opportunity.deadline, fmt).date()
                if d < date.today():
                    blockers.append(f"deadline passed on {d.isoformat()}")
                break
            except ValueError:
                continue

    hard = nofo.hard_reject or any(b.startswith("deadline passed") for b in blockers)
    score = 0 if hard else nofo.fit_score

    if hard:
        priority = "REJECT"
    elif score >= 80:
        priority = "HIGH"
    elif score >= 60:
        priority = "MEDIUM"
    elif score >= 40:
        priority = "LOW"
    else:
        priority = "VERY_LOW"

    facts = _load_facts()
    missing = [
        f"{f.get('category', 'general')}.{f.get('key', '')}"
        for f in facts
        if str(f.get("status", "")).upper() == "MISSING"
    ]

    writer_packages = []

    if generate_drafts and not hard:
        provider = OllamaProvider()
        health = provider.health()
        if not health.get("available") or not health.get("model_installed"):
            raise RuntimeError(f"Ollama not ready: {health}")

        for question in nofo.application_questions:
            relevant = _relevant(question, facts)
            result = write_answer(
                question=question,
                section="general",
                facts=relevant,
                grant_title=opportunity.title,
                funder=opportunity.funder,
                priorities=nofo.priorities,
                requirements=nofo.requirements,
                provider=provider,
            )
            writer_packages.append(result.to_dict())

    readiness = 0 if hard else min(
        100,
        50
        + min(20, len(nofo.application_questions) * 3)
        + (20 if not missing else max(0, 20 - len(missing) * 2))
        + min(10, sum(1 for p in writer_packages if p.get("status") == "READY_FOR_HUMAN_REVIEW") * 2),
    )

    return {
        "id": opportunity.id,
        "title": opportunity.title,
        "funder": opportunity.funder,
        "score": score,
        "priority": priority,
        "hard_reject": hard,
        "blockers": blockers,
        "deadline": opportunity.deadline,
        "amount": opportunity.amount,
        "source_url": opportunity.source_url,
        "matched_domains": nofo.matched_domains,
        "nofo": nofo.to_dict(),
        "missing_information": missing,
        "readiness_score": readiness,
        "writer_packages": writer_packages,
    }


def rank_opportunities(
    opportunities: list[Opportunity],
    *,
    generate_drafts: bool = False,
) -> list[dict[str, Any]]:
    seen = set()
    unique = []

    for item in opportunities:
        key = item.id.strip().lower() or (
            item.title.strip().lower(),
            item.funder.strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    results = [
        analyze_opportunity(item, generate_drafts=generate_drafts)
        for item in unique
    ]

    return sorted(
        results,
        key=lambda x: (
            x["hard_reject"],
            -x["score"],
            -x["readiness_score"],
            x["title"].lower(),
        ),
    )
PY

cat > grantbot/api/master_pipeline_v5.py <<'PY'
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.automation.opportunity_pipeline import Opportunity, rank_opportunities
from grantbot.writing.ollama_provider import OllamaProvider


router = APIRouter(
    prefix="/v5/opportunities",
    tags=["GrantBot Full Opportunity Automation v5"],
)


class OpportunityPayload(BaseModel):
    id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=2, max_length=2000)
    funder: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=100000)
    eligibility: str = Field(default="", max_length=50000)
    deadline: str | None = Field(default=None, max_length=100)
    amount: float | None = Field(default=None, ge=0)
    source_url: str = Field(default="", max_length=5000)
    nofo_text: str = Field(default="", max_length=2_000_000)


class BatchRequest(BaseModel):
    opportunities: list[OpportunityPayload] = Field(min_length=1, max_length=500)
    generate_drafts: bool = False


@router.get("/health")
def health() -> dict[str, Any]:
    return OllamaProvider().health()


@router.post("/analyze")
def analyze(payload: BatchRequest) -> dict[str, Any]:
    try:
        results = rank_opportunities(
            [
                Opportunity(**item.model_dump())
                for item in payload.opportunities
            ],
            generate_drafts=payload.generate_drafts,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "count": len(results),
        "high_priority": sum(1 for x in results if x["priority"] == "HIGH"),
        "rejected": sum(1 for x in results if x["hard_reject"]),
        "results": results,
    }
PY

cat > tests/test_master_v3_v5.py <<'PY'
from __future__ import annotations

import unittest

from grantbot.automation.opportunity_pipeline import Opportunity, rank_opportunities
from grantbot.nofo.analyzer import analyze_nofo
from grantbot.writing.quality_gate import evaluate_draft


class MasterV3V5Tests(unittest.TestCase):
    def test_quality_rejects_unsupported_number(self) -> None:
        result = evaluate_draft(
            question="How many people?",
            draft="We will serve 500 people.",
            facts=[{"value": "People experiencing homelessness"}],
            max_words=100,
        )
        self.assertFalse(result.passed)
        self.assertIn("500", result.unsupported_numbers)

    def test_nofo_strong_fit(self) -> None:
        result = analyze_nofo(
            """
            Eligible applicants include nonprofit and faith-based organizations.
            Florida reentry homelessness supportive housing employment workforce
            development job training case management supportive services.
            1. Describe your organization mission?
            """
        )
        self.assertGreaterEqual(result.fit_score, 80)
        self.assertEqual(result.priority, "HIGH")

    def test_hard_reject(self) -> None:
        result = analyze_nofo(
            """
            Eligibility: Postdoctoral applicants only.
            This program funds research.
            """
        )
        self.assertTrue(result.hard_reject)
        self.assertEqual(result.priority, "REJECT")

    def test_rank(self) -> None:
        results = rank_opportunities(
            [
                Opportunity(
                    id="weak",
                    title="Museum",
                    description="Historic preservation",
                    deadline="2099-12-01",
                ),
                Opportunity(
                    id="strong",
                    title="Florida Reentry Housing Workforce",
                    description=(
                        "reentry homelessness housing employment workforce "
                        "supportive services Florida"
                    ),
                    eligibility="nonprofit organizations",
                    deadline="2099-12-01",
                ),
            ]
        )
        self.assertEqual(results[0]["id"], "strong")
        self.assertGreaterEqual(results[0]["score"], 80)


if __name__ == "__main__":
    unittest.main()
PY

python - <<'PY'
from pathlib import Path

p = Path("grantbot/app.py")
text = p.read_text(encoding="utf-8")

imp = (
    "from grantbot.api.master_pipeline_v5 "
    "import router as master_pipeline_v5_router"
)
reg = "app.include_router(master_pipeline_v5_router)"

if imp not in text:
    text += "\n" + imp + "\n"

if reg not in text:
    text += reg + "\n"

p.write_text(text, encoding="utf-8")
print("REGISTERED: /v5/opportunities")
PY

python -m py_compile \
  grantbot/writing/ollama_provider.py \
  grantbot/writing/quality_gate.py \
  grantbot/writing/master_writer.py \
  grantbot/nofo/analyzer.py \
  grantbot/automation/opportunity_pipeline.py \
  grantbot/api/master_pipeline_v5.py \
  tests/test_master_v3_v5.py

python -m unittest tests.test_master_v3_v5 -v
python -m compileall -q grantbot
python -c "import grantbot.app; print('GRANTBOT APP IMPORT: OK')"

echo "============================================================"
echo " MASTER V3-V5 INSTALL COMPLETE"
echo "============================================================"
echo "GET  /v5/opportunities/health"
echo "POST /v5/opportunities/analyze"
