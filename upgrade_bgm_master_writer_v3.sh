#!/usr/bin/env bash
set -euo pipefail

SEARCH_ROOT="${HOME}/grantbot_pro"
SCRIPT_NAME="upgrade_bgm_master_writer_v3.sh"

echo "============================================================"
echo " BrokenGrowthMinistries GrantBot"
echo " Master Ollama Writer + Quality Gate v3"
echo "============================================================"

APP_FILE="$(find "$SEARCH_ROOT" -maxdepth 7 -type f -path '*/grantbot/app.py' -print -quit 2>/dev/null || true)"

if [[ -z "$APP_FILE" ]]; then
    echo "ERROR: Existing grantbot/app.py was not found under $SEARCH_ROOT." >&2
    echo "No fake application will be created." >&2
    find "$SEARCH_ROOT" -maxdepth 6 -type f -name 'app.py' -print 2>/dev/null || true
    exit 1
fi

ROOT="$(dirname "$(dirname "$APP_FILE")")"
cd "$ROOT"

if [[ -d "$ROOT/.venv" ]]; then
    VENV="$ROOT/.venv"
elif [[ -d "$SEARCH_ROOT/.venv" ]]; then
    VENV="$SEARCH_ROOT/.venv"
else
    echo "ERROR: Existing GrantBot virtual environment was not found." >&2
    exit 1
fi

source "$VENV/bin/activate"

echo "PROJECT ROOT: $ROOT"
echo "VENV:         $VENV"
echo "PYTHON:       $(command -v python)"

STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p backups grantbot/writing grantbot/api tests

for target in \
    grantbot/writing/master_writer.py \
    grantbot/writing/ollama_provider.py \
    grantbot/writing/quality_gate.py \
    grantbot/api/master_writer_v3.py
do
    if [[ -f "$target" ]]; then
        cp "$target" "backups/$(basename "$target").${STAMP}.bak"
    fi
done

cp grantbot/app.py "backups/app_before_master_writer_v3_${STAMP}.py"

touch grantbot/writing/__init__.py
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
    base_url: str
    model: str
    timeout_seconds: int = 300

    @classmethod
    def from_env(cls) -> "OllamaConfig":
        base_url = os.getenv(
            "OLLAMA_URL",
            "http://127.0.0.1:11434",
        ).rstrip("/")

        model = os.getenv(
            "OLLAMA_MODEL",
            "llama3.2:3b",
        ).strip()

        if not model:
            raise RuntimeError(
                "OLLAMA_MODEL cannot be empty."
            )

        return cls(
            base_url=base_url,
            model=model,
        )


class OllamaProvider:
    def __init__(
        self,
        config: OllamaConfig | None = None,
    ) -> None:
        self.config = config or OllamaConfig.from_env()

    def generate(
        self,
        prompt: str,
        *,
        system: str,
        temperature: float = 0.35,
    ) -> str:
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        if not system.strip():
            raise ValueError("System prompt cannot be empty.")

        if not 0.0 <= temperature <= 1.0:
            raise ValueError(
                "temperature must be between 0.0 and 1.0"
            )

        payload: dict[str, Any] = {
            "model": self.config.model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        request = Request(
            f"{self.config.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.config.timeout_seconds,
            ) as response:
                raw = response.read().decode("utf-8")

        except HTTPError as exc:
            detail = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            raise RuntimeError(
                f"Ollama HTTP {exc.code}: {detail}"
            ) from exc

        except URLError as exc:
            raise RuntimeError(
                "Ollama is unavailable at "
                f"{self.config.base_url}: {exc.reason}"
            ) from exc

        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Ollama returned invalid JSON."
            ) from exc

        text = body.get("response")

        if not isinstance(text, str) or not text.strip():
            raise RuntimeError(
                "Ollama returned an empty response."
            )

        return text.strip()

    def health(self) -> dict[str, Any]:
        request = Request(
            f"{self.config.base_url}/api/tags",
            method="GET",
        )

        try:
            with urlopen(
                request,
                timeout=10,
            ) as response:
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError) as exc:
            return {
                "available": False,
                "model": self.config.model,
                "error": str(exc),
            }

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
PY

cat > grantbot/writing/quality_gate.py <<'PY'
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


NUMBER_RE = re.compile(
    r"(?<![\w])(?:\$?\d[\d,]*(?:\.\d+)?%?)(?![\w])"
)

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

GENERIC_PHRASES = (
    "make a difference",
    "change lives",
    "unique opportunity",
    "transformative impact",
    "deserving organization",
    "we believe",
    "we hope",
)

UNSAFE_CERTAINTY = (
    "will eliminate",
    "will guarantee",
    "will ensure",
    "proven success",
    "demonstrated success",
    "track record of success",
)


@dataclass(frozen=True, slots=True)
class QualityResult:
    passed: bool
    score: int
    word_count: int
    issues: list[str]
    strengths: list[str]
    unsupported_numbers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fact_text(
    facts: Iterable[dict[str, Any]],
) -> str:
    values = []

    for fact in facts:
        value = fact.get("value", fact.get("answer"))

        if value not in (None, "", [], {}):
            values.append(str(value))

    return " ".join(values).lower()


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
        return QualityResult(
            passed=False,
            score=0,
            word_count=0,
            issues=["Draft is empty."],
            strengths=[],
            unsupported_numbers=[],
        )

    word_count = len(text.split())
    issues: list[str] = []
    strengths: list[str] = []
    score = 100

    source = _fact_text(facts)

    unsupported_numbers = sorted(
        {
            number
            for number in NUMBER_RE.findall(text)
            if number.lower() not in source
        }
    )

    if unsupported_numbers:
        score -= min(
            45,
            15 * len(unsupported_numbers),
        )
        issues.append(
            "Unsupported numeric claim(s): "
            + ", ".join(unsupported_numbers)
        )
    else:
        strengths.append(
            "No unsupported numeric claims detected."
        )

    if max_words is not None:
        if max_words < 1:
            raise ValueError(
                "max_words must be positive."
            )

        if word_count > max_words:
            score -= 25
            issues.append(
                f"Word limit exceeded: {word_count}/{max_words}."
            )
        else:
            strengths.append(
                f"Within word limit: {word_count}/{max_words}."
            )

    required_terms = [
        term.strip().lower()
        for term in (required_terms or [])
        if term.strip()
    ]

    missing_terms = [
        term
        for term in required_terms
        if term not in text.lower()
    ]

    if missing_terms:
        score -= min(
            25,
            5 * len(missing_terms),
        )
        issues.append(
            "Funder priority terms not addressed: "
            + ", ".join(missing_terms)
        )
    elif required_terms:
        strengths.append(
            "Addresses supplied funder priorities."
        )

    lower = text.lower()

    clichés = [
        phrase
        for phrase in GENERIC_PHRASES
        if phrase in lower
    ]

    if clichés:
        score -= min(15, len(clichés) * 5)
        issues.append(
            "Generic/cliché language detected: "
            + ", ".join(clichés)
        )

    certainty = [
        phrase
        for phrase in UNSAFE_CERTAINTY
        if phrase in lower
        and phrase not in source
    ]

    if certainty:
        score -= min(30, len(certainty) * 10)
        issues.append(
            "Unsupported certainty/result claim detected: "
            + ", ".join(certainty)
        )

    question_terms = {
        token
        for token in re.findall(
            r"[a-zA-Z]{4,}",
            question.lower(),
        )
    }

    if question_terms:
        overlap = sum(
            1
            for token in question_terms
            if token in lower
        )

        if overlap:
            strengths.append(
                "Draft is lexically connected to the question."
            )
        else:
            score -= 15
            issues.append(
                "Draft may not answer the question directly."
            )

    if len(SENTENCE_RE.split(text)) >= 2:
        strengths.append(
            "Draft has developed narrative structure."
        )

    score = max(0, min(100, score))

    return QualityResult(
        passed=score >= 80 and not unsupported_numbers,
        score=score,
        word_count=word_count,
        issues=issues,
        strengths=strengths,
        unsupported_numbers=unsupported_numbers,
    )
PY

cat > grantbot/writing/master_writer.py <<'PY'
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from grantbot.writing.ollama_provider import OllamaProvider
from grantbot.writing.quality_gate import evaluate_draft


TRUSTED_STATUSES = {"VERIFIED", "APPROVED"}
PLANNING_STATUSES = {"DRAFT"}


SECTION_STRATEGIES: dict[str, str] = {
    "executive_summary": (
        "Lead with mission fit, community problem, intervention, "
        "credible expected value, and a concise investment case."
    ),
    "statement_of_need": (
        "Define the human and community problem precisely. "
        "Connect barriers logically. Use only supplied evidence. "
        "Do not manufacture prevalence, recidivism, homelessness, "
        "or cost statistics."
    ),
    "program_design": (
        "Explain who will do what, for whom, how, where, and in "
        "what sequence. Clearly label planned activities as planned."
    ),
    "goals_objectives": (
        "Use measurable language only where targets are supplied. "
        "If targets are missing, describe the intended direction "
        "without inventing numbers."
    ),
    "outcomes_evaluation": (
        "Separate outputs, outcomes, and evaluation methods. "
        "Never convert proposed outcomes into demonstrated results."
    ),
    "organizational_capacity": (
        "Build credibility from verified leadership, experience, "
        "partnerships, systems, and governance only."
    ),
    "sustainability": (
        "Explain realistic continuation mechanisms supported by "
        "facts. Do not promise unidentified future funding."
    ),
    "budget_narrative": (
        "Connect requested costs to program delivery and outcomes. "
        "Never invent line items, costs, percentages, or match."
    ),
    "partnerships": (
        "Describe only verified or approved partners and their "
        "documented roles. Do not imply commitments that do not exist."
    ),
    "general": (
        "Answer the exact question directly, then support the answer "
        "with the strongest relevant trusted facts."
    ),
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


def _normalize_fact(
    raw: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": str(raw.get("id", "")).strip(),
        "category": str(
            raw.get("category", "general")
        ).strip().lower(),
        "key": str(raw.get("key", "")).strip(),
        "value": raw.get(
            "value",
            raw.get("answer"),
        ),
        "status": str(
            raw.get("status", "APPROVED")
        ).strip().upper(),
        "source": str(
            raw.get("source", "unknown")
        ).strip(),
        "notes": str(
            raw.get("notes", "")
        ).strip(),
    }


def _partition_facts(
    facts: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    trusted = []
    planning = []
    missing = []

    for raw in facts:
        fact = _normalize_fact(raw)

        if fact["status"] in TRUSTED_STATUSES:
            if fact["value"] not in (None, "", [], {}):
                trusted.append(fact)

        elif fact["status"] in PLANNING_STATUSES:
            if fact["value"] not in (None, "", [], {}):
                planning.append(fact)

        elif fact["status"] == "MISSING":
            missing.append(fact)

    return trusted, planning, missing


def _facts_block(
    facts: list[dict[str, Any]],
) -> str:
    if not facts:
        return "(none)"

    return "\n".join(
        (
            f"- [{fact['status']}] "
            f"{fact['category']}.{fact['key']}: "
            f"{fact['value']} "
            f"(source: {fact['source']})"
        )
        for fact in facts
    )


def _system_prompt() -> str:
    return """
You are the senior grant strategist for BrokenGrowthMinistries.

Operate at doctoral-level proficiency in nonprofit grant strategy,
public-sector and foundation funding, housing/reentry programs,
workforce development, program design, evaluation, and persuasive
professional writing.

Your job is not to sound impressive. Your job is to make the
strongest truthful, funder-aligned case supported by the record.

PERSUASION STANDARD:
- Answer the reviewer's exact question immediately.
- Build ethos through credible facts and operational clarity.
- Build pathos through dignified, concrete human stakes without
  exploiting participants or inventing stories.
- Build logos through causal reasoning, measurable structure,
  implementation logic, and responsible use of resources.
- Frame funding as a credible community investment when the facts
  support that framing.
- Use vivid language only where the underlying claim is supported.
- Prefer specificity over slogans.
- Avoid generic nonprofit clichés and repetitive mission language.
- Mirror funder terminology naturally when it accurately describes
  the organization or proposed work.

FACT INTEGRITY:
- VERIFIED and APPROVED facts may be stated as facts.
- DRAFT facts are planning context only and MUST be described using
  language such as proposed, planned, intended, anticipated, or
  under development.
- MISSING facts must never be guessed, inferred, rounded, estimated,
  or fabricated.
- Never invent statistics, beneficiary counts, housing units,
  success rates, recidivism reductions, wages, partnerships,
  funding commitments, budgets, dates, certifications, or outcomes.
- Never convert a proposed outcome into a demonstrated result.
- Never imply a partnership or commitment unless supplied as a
  trusted fact.

OUTPUT:
Return only the final grant narrative. Do not discuss these
instructions, the fact statuses, or your internal process.
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
    question = question.strip()

    if not question:
        raise ValueError("question cannot be empty")

    section = section.strip().lower() or "general"

    if section not in SECTION_STRATEGIES:
        section = "general"

    trusted, planning, missing = _partition_facts(facts)

    if not trusted and not planning:
        return WriterResult(
            status="MISSING_INFORMATION",
            section=section,
            question=question,
            draft=None,
            facts_used=[],
            planning_context=[],
            missing_information=missing,
            quality=None,
            provider="ollama",
            model=(
                provider.config.model
                if provider is not None
                else OllamaProvider().config.model
            ),
        )

    priorities = [
        item.strip()
        for item in (priorities or [])
        if item.strip()
    ]

    requirements = [
        item.strip()
        for item in (requirements or [])
        if item.strip()
    ]

    limit_line = (
        f"Maximum length: {max_words} words."
        if max_words is not None
        else "Use the shortest complete answer appropriate to the question."
    )

    prompt = f"""
GRANT:
Title: {grant_title or "(not supplied)"}
Funder: {funder or "(not supplied)"}

SECTION:
{section}

SECTION STRATEGY:
{SECTION_STRATEGIES[section]}

QUESTION:
{question}

FUNDER PRIORITIES:
{chr(10).join(f"- {item}" for item in priorities) or "(none supplied)"}

OTHER REQUIREMENTS:
{chr(10).join(f"- {item}" for item in requirements) or "(none supplied)"}

TRUSTED FACTS:
{_facts_block(trusted)}

PLANNING CONTEXT:
{_facts_block(planning)}

KNOWN MISSING INFORMATION:
{_facts_block(missing)}

LENGTH:
{limit_line}

Write the strongest submission-quality answer possible from this
record. Do not fill factual gaps. Planning context must remain
clearly prospective.
""".strip()

    active_provider = provider or OllamaProvider()

    draft = active_provider.generate(
        prompt,
        system=_system_prompt(),
        temperature=0.3,
    )

    quality = evaluate_draft(
        question=question,
        draft=draft,
        facts=trusted + planning,
        max_words=max_words,
        required_terms=priorities,
    )

    status = (
        "READY_FOR_HUMAN_REVIEW"
        if quality.passed
        else "REVISION_REQUIRED"
    )

    return WriterResult(
        status=status,
        section=section,
        question=question,
        draft=draft,
        facts_used=trusted,
        planning_context=planning,
        missing_information=missing,
        quality=quality.to_dict(),
        provider="ollama",
        model=active_provider.config.model,
    )
PY

cat > grantbot/api/master_writer_v3.py <<'PY'
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.writing.master_writer import write_answer
from grantbot.writing.ollama_provider import OllamaProvider


router = APIRouter(
    prefix="/v3/writer",
    tags=["GrantBot Master Writer v3"],
)


class FactPayload(BaseModel):
    id: str = ""
    category: str = "general"
    key: str = ""
    value: Any = None
    answer: Any = None
    status: Literal[
        "VERIFIED",
        "APPROVED",
        "DRAFT",
        "MISSING",
    ] = "APPROVED"
    source: str = "api"
    notes: str = ""


class MasterWriterRequest(BaseModel):
    question: str = Field(
        min_length=3,
        max_length=10000,
    )
    section: str = Field(
        default="general",
        max_length=100,
    )
    facts: list[FactPayload] = Field(
        default_factory=list,
        max_length=100,
    )
    grant_title: str = Field(
        default="",
        max_length=1000,
    )
    funder: str = Field(
        default="",
        max_length=1000,
    )
    priorities: list[str] = Field(
        default_factory=list,
        max_length=30,
    )
    requirements: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    max_words: int | None = Field(
        default=None,
        ge=25,
        le=5000,
    )


@router.get("/health")
def health() -> dict[str, Any]:
    return OllamaProvider().health()


@router.post("/draft")
def draft(
    payload: MasterWriterRequest,
) -> dict[str, Any]:
    provider = OllamaProvider()

    health_state = provider.health()

    if not health_state.get("available"):
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ollama is unavailable.",
                "ollama": health_state,
            },
        )

    if not health_state.get("model_installed"):
        raise HTTPException(
            status_code=503,
            detail={
                "message": (
                    "Configured Ollama model is not installed. "
                    "Run: ollama pull "
                    f"{provider.config.model}"
                ),
                "ollama": health_state,
            },
        )

    result = write_answer(
        question=payload.question,
        section=payload.section,
        facts=[
            fact.model_dump()
            for fact in payload.facts
        ],
        grant_title=payload.grant_title,
        funder=payload.funder,
        priorities=payload.priorities,
        requirements=payload.requirements,
        max_words=payload.max_words,
        provider=provider,
    )

    return result.to_dict()
PY

cat > tests/test_master_writer_v3.py <<'PY'
from __future__ import annotations

import unittest

from grantbot.writing.master_writer import (
    _partition_facts,
)
from grantbot.writing.quality_gate import (
    evaluate_draft,
)


class MasterWriterV3Tests(unittest.TestCase):
    def test_fact_partition(self) -> None:
        trusted, planning, missing = _partition_facts(
            [
                {
                    "id": "A",
                    "category": "mission",
                    "key": "vision",
                    "value": "Approved vision",
                    "status": "APPROVED",
                    "source": "founder",
                },
                {
                    "id": "B",
                    "category": "housing",
                    "key": "plan",
                    "value": "Tiny homes are planned",
                    "status": "DRAFT",
                    "source": "planning",
                },
                {
                    "id": "C",
                    "category": "financial",
                    "key": "budget",
                    "value": None,
                    "status": "MISSING",
                    "source": "queue",
                },
            ]
        )

        self.assertEqual(len(trusted), 1)
        self.assertEqual(len(planning), 1)
        self.assertEqual(len(missing), 1)

    def test_quality_rejects_unsupported_number(self) -> None:
        result = evaluate_draft(
            question="How many people will you serve?",
            draft="The program will serve 500 people.",
            facts=[
                {
                    "value":
                        "The program serves people experiencing homelessness."
                }
            ],
            max_words=100,
        )

        self.assertFalse(result.passed)
        self.assertIn(
            "500",
            result.unsupported_numbers,
        )

    def test_quality_accepts_supported_number(self) -> None:
        result = evaluate_draft(
            question="How many people will you serve?",
            draft="The program plans to serve 50 people.",
            facts=[
                {
                    "value":
                        "The approved target is 50 people."
                }
            ],
            max_words=100,
        )

        self.assertNotIn(
            "50",
            result.unsupported_numbers,
        )

    def test_word_limit(self) -> None:
        result = evaluate_draft(
            question="Describe the mission.",
            draft="one two three four five six",
            facts=[{"value": "mission"}],
            max_words=5,
        )

        self.assertFalse(result.passed)
        self.assertTrue(
            any(
                "Word limit exceeded"
                in issue
                for issue in result.issues
            )
        )


if __name__ == "__main__":
    unittest.main()
PY

python - <<'PY'
from pathlib import Path

p = Path("grantbot/app.py")
text = p.read_text(encoding="utf-8")

imp = (
    "from grantbot.api.master_writer_v3 "
    "import router as master_writer_v3_router"
)

reg = "app.include_router(master_writer_v3_router)"

if imp not in text:
    text += "\n" + imp + "\n"

if reg not in text:
    text += reg + "\n"

p.write_text(
    text,
    encoding="utf-8",
)

print("Registered /v3/writer router")
PY

python -m py_compile \
    grantbot/writing/ollama_provider.py \
    grantbot/writing/quality_gate.py \
    grantbot/writing/master_writer.py \
    grantbot/api/master_writer_v3.py \
    tests/test_master_writer_v3.py

python -m unittest tests.test_master_writer_v3 -v

python -m compileall -q grantbot

python -c \
"import grantbot.app; print('GRANTBOT APP IMPORT: OK')"

echo
echo "============================================================"
echo " MASTER WRITER V3 INSTALLED"
echo "============================================================"
echo "GET  /v3/writer/health"
echo "POST /v3/writer/draft"
echo
echo "Start GrantBot:"
echo "  cd \"$ROOT\""
echo "  source \"$VENV/bin/activate\""
echo "  python -m uvicorn grantbot.app:app --reload"
echo
echo "Ollama model:"
echo "  ${OLLAMA_MODEL:-llama3.2:3b}"
echo "============================================================"
