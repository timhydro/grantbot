#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/grantbot_pro"
cd "$ROOT"

if [[ ! -f grantbot/app.py ]]; then
  echo "ERROR: grantbot/app.py not found." >&2
  exit 1
fi

if [[ ! -f grantbot/automation/opportunity_pipeline.py ]]; then
  echo "ERROR: v5 opportunity pipeline missing." >&2
  exit 1
fi

if [[ ! -f grantbot/writing/master_writer.py ]]; then
  echo "ERROR: Master Writer v3 missing." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "ERROR: $ROOT/.venv not found." >&2
  exit 1
fi

source .venv/bin/activate

STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p backups grantbot/applications grantbot/api tests data/applications

for target in \
  grantbot/applications/package_builder.py \
  grantbot/api/application_v7.py
do
  if [[ -f "$target" ]]; then
    cp "$target" "backups/$(basename "$target").${STAMP}.bak"
  fi
done

cp grantbot/app.py "backups/app_before_application_v7_${STAMP}.py"

touch grantbot/applications/__init__.py
touch grantbot/api/__init__.py

cat > grantbot/applications/package_builder.py <<'PY'
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from grantbot.automation.opportunity_pipeline import Opportunity, analyze_opportunity
from grantbot.writing.master_writer import write_answer
from grantbot.writing.ollama_provider import OllamaProvider


SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class ApplicationPackage:
    package_id: str
    created_at: str
    opportunity: dict[str, Any]
    readiness_score: int
    status: str
    missing_information: list[str]
    questions: list[dict[str, Any]]
    output_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_id(value: str) -> str:
    cleaned = SAFE_ID_RE.sub("_", value.strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        raise ValueError("package id cannot be empty")
    return cleaned[:120]


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name,
        suffix=".tmp",
        dir=str(path.parent),
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                data,
                handle,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(tmp_name, path)

    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _load_facts() -> list[dict[str, Any]]:
    try:
        from grantbot.knowledge.fact_registry import FactRegistry
    except ImportError:
        return []

    registry = FactRegistry()

    raw = None

    if hasattr(registry, "all") and callable(registry.all):
        raw = registry.all()
    elif hasattr(registry, "get_all") and callable(registry.get_all):
        raw = registry.get_all()
    elif hasattr(registry, "get_all_facts") and callable(registry.get_all_facts):
        raw = registry.get_all_facts()
    elif hasattr(registry, "_facts"):
        raw = registry._facts

    if raw is None:
        return []

    if isinstance(raw, dict):
        if isinstance(raw.get("facts"), list):
            raw = raw["facts"]
        else:
            raw = [
                {
                    "id": str(key),
                    "category": "general",
                    "key": str(key),
                    "value": value,
                    "status": "APPROVED",
                    "source": "legacy_fact_registry",
                }
                for key, value in raw.items()
            ]

    facts: list[dict[str, Any]] = []

    for item in raw:
        if hasattr(item, "to_dict") and callable(item.to_dict):
            fact = item.to_dict()
        elif isinstance(item, dict):
            fact = dict(item)
        else:
            continue

        fact.setdefault("id", str(fact.get("key", "")))
        fact.setdefault("category", "general")
        fact.setdefault("key", fact.get("id", ""))
        fact.setdefault("status", "APPROVED")
        fact.setdefault("source", "fact_registry")
        facts.append(fact)

    return facts


def _tokens(text: str) -> set[str]:
    cleaned = "".join(
        ch.lower() if ch.isalnum() else " "
        for ch in text
    )
    return {
        token
        for token in cleaned.split()
        if len(token) >= 4
    }


def _relevant_facts(
    question: str,
    facts: list[dict[str, Any]],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    query = _tokens(question)
    scored: list[tuple[int, dict[str, Any]]] = []

    for fact in facts:
        status = str(fact.get("status", "")).upper()

        if status not in {"VERIFIED", "APPROVED", "DRAFT", "MISSING"}:
            continue

        searchable = " ".join(
            (
                str(fact.get("category", "")),
                str(fact.get("key", "")),
                str(fact.get("value", fact.get("answer", ""))),
            )
        ).lower()

        score = sum(
            1
            for token in query
            if token in searchable
        )

        if status == "MISSING":
            score += 1

        if score > 0:
            scored.append((score, fact))

    scored.sort(
        key=lambda pair: (
            -pair[0],
            str(pair[1].get("category", "")),
            str(pair[1].get("key", "")),
        )
    )

    return [
        fact
        for _, fact in scored[:limit]
    ]


def _package_status(
    *,
    hard_reject: bool,
    answers: list[dict[str, Any]],
    missing: list[str],
) -> str:
    if hard_reject:
        return "REJECTED"

    if missing:
        return "NEEDS_INFORMATION"

    if answers and all(
        item.get("status") == "READY_FOR_HUMAN_REVIEW"
        for item in answers
    ):
        return "READY_FOR_HUMAN_REVIEW"

    return "REVISION_REQUIRED"


def build_application_package(
    opportunity: Opportunity,
    *,
    generate_drafts: bool = True,
    output_root: Path | None = None,
) -> ApplicationPackage:
    analyzed = analyze_opportunity(
        opportunity,
        generate_drafts=False,
    )

    questions: list[str] = []

    nofo = analyzed.get("nofo")

    if isinstance(nofo, dict):
        questions = [
            str(item).strip()
            for item in nofo.get("application_questions", [])
            if str(item).strip()
        ]

    facts = _load_facts()

    answers: list[dict[str, Any]] = []

    if generate_drafts and not analyzed.get("hard_reject", False):
        provider = OllamaProvider()
        health = provider.health()

        if not health.get("available"):
            raise RuntimeError(
                f"Ollama unavailable: {health}"
            )

        if not health.get("model_installed"):
            raise RuntimeError(
                f"Ollama model not installed: {provider.config.model}"
            )

        priorities = []

        requirements = []

        if isinstance(nofo, dict):
            priorities = [
                str(item)
                for item in nofo.get("priorities", [])
            ]

            requirements = [
                str(item)
                for item in nofo.get("requirements", [])
            ]

        for question in questions:
            relevant = _relevant_facts(
                question,
                facts,
            )

            result = write_answer(
                question=question,
                section="general",
                facts=relevant,
                grant_title=opportunity.title,
                funder=opportunity.funder,
                priorities=priorities,
                requirements=requirements,
                provider=provider,
            )

            answers.append(
                result.to_dict()
            )

    missing = list(
        dict.fromkeys(
            str(item)
            for item in analyzed.get("missing_information", [])
            if str(item).strip()
        )
    )

    base_readiness = int(
        analyzed.get("readiness_score", 0)
    )

    if answers:
        quality_scores = [
            int(
                (item.get("quality") or {}).get(
                    "score",
                    0,
                )
            )
            for item in answers
        ]

        average_quality = (
            sum(quality_scores)
            // len(quality_scores)
        )

        readiness = min(
            100,
            round(
                base_readiness * 0.5
                + average_quality * 0.5
            ),
        )
    else:
        readiness = base_readiness

    package_id = _safe_id(
        opportunity.id
        or opportunity.title
    )

    output_root = output_root or (
        Path(__file__).resolve().parents[2]
        / "data"
        / "applications"
    )

    output_path = (
        output_root
        / package_id
        / "application_package.json"
    )

    created_at = datetime.now(
        timezone.utc
    ).isoformat()

    status = _package_status(
        hard_reject=bool(
            analyzed.get("hard_reject")
        ),
        answers=answers,
        missing=missing,
    )

    package = ApplicationPackage(
        package_id=package_id,
        created_at=created_at,
        opportunity=analyzed,
        readiness_score=readiness,
        status=status,
        missing_information=missing,
        questions=answers,
        output_path=str(output_path),
    )

    _atomic_write_json(
        output_path,
        package.to_dict(),
    )

    return package


def load_application_package(
    package_id: str,
    *,
    output_root: Path | None = None,
) -> dict[str, Any]:
    safe_id = _safe_id(package_id)

    output_root = output_root or (
        Path(__file__).resolve().parents[2]
        / "data"
        / "applications"
    )

    path = (
        output_root
        / safe_id
        / "application_package.json"
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Application package not found: {safe_id}"
        )

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(data, dict):
        raise RuntimeError(
            "Stored application package is invalid."
        )

    return data
PY

cat > grantbot/api/application_v7.py <<'PY'
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.applications.package_builder import (
    build_application_package,
    load_application_package,
)
from grantbot.automation.opportunity_pipeline import Opportunity


router = APIRouter(
    prefix="/v7/applications",
    tags=["GrantBot Application Package Builder v7"],
)


class BuildRequest(BaseModel):
    id: str = Field(
        min_length=1,
        max_length=500,
    )
    title: str = Field(
        min_length=2,
        max_length=2000,
    )
    funder: str = Field(
        default="",
        max_length=2000,
    )
    description: str = Field(
        default="",
        max_length=100000,
    )
    eligibility: str = Field(
        default="",
        max_length=50000,
    )
    deadline: str | None = Field(
        default=None,
        max_length=100,
    )
    amount: float | None = Field(
        default=None,
        ge=0,
    )
    source_url: str = Field(
        default="",
        max_length=5000,
    )
    nofo_text: str = Field(
        default="",
        max_length=2_000_000,
    )
    generate_drafts: bool = True


@router.post("/build")
def build(
    payload: BuildRequest,
) -> dict[str, Any]:
    try:
        opportunity = Opportunity(
            id=payload.id,
            title=payload.title,
            funder=payload.funder,
            description=payload.description,
            eligibility=payload.eligibility,
            deadline=payload.deadline,
            amount=payload.amount,
            source_url=payload.source_url,
            nofo_text=payload.nofo_text,
        )

        return build_application_package(
            opportunity,
            generate_drafts=payload.generate_drafts,
        ).to_dict()

    except (
        RuntimeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.get("/{package_id}")
def get_package(
    package_id: str,
) -> dict[str, Any]:
    try:
        return load_application_package(
            package_id
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
PY

cat > tests/test_application_v7.py <<'PY'
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grantbot.applications.package_builder import (
    build_application_package,
    load_application_package,
)
from grantbot.automation.opportunity_pipeline import Opportunity


class ApplicationV7Tests(unittest.TestCase):
    def test_build_without_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            opportunity = Opportunity(
                id="test-package",
                title="Florida Reentry Workforce",
                description=(
                    "reentry homelessness housing employment "
                    "workforce supportive services Florida"
                ),
                eligibility="nonprofit organizations",
                deadline="2099-12-01",
                nofo_text=(
                    "Nonprofit organizations may apply. "
                    "This program supports reentry housing employment. "
                    "1. Describe your organization mission?"
                ),
            )

            package = build_application_package(
                opportunity,
                generate_drafts=False,
                output_root=Path(td),
            )

            self.assertEqual(
                package.package_id,
                "test-package",
            )

            self.assertTrue(
                Path(package.output_path).exists()
            )

            loaded = load_application_package(
                "test-package",
                output_root=Path(td),
            )

            self.assertEqual(
                loaded["package_id"],
                "test-package",
            )

    def test_safe_package_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            opportunity = Opportunity(
                id="../../bad id",
                title="Test",
                description="housing employment reentry",
                eligibility="nonprofit",
                deadline="2099-12-01",
            )

            package = build_application_package(
                opportunity,
                generate_drafts=False,
                output_root=Path(td),
            )

            self.assertNotIn(
                "..",
                package.package_id,
            )

            self.assertNotIn(
                "/",
                package.package_id,
            )


if __name__ == "__main__":
    unittest.main()
PY

python3 - <<'PY'
from pathlib import Path

p = Path("grantbot/app.py")
text = p.read_text(
    encoding="utf-8"
)

imp = (
    "from grantbot.api.application_v7 "
    "import router as application_v7_router"
)

reg = "app.include_router(application_v7_router)"

if imp not in text:
    text += "\n" + imp + "\n"

if reg not in text:
    text += reg + "\n"

p.write_text(
    text,
    encoding="utf-8",
)

print(
    "REGISTERED: /v7/applications"
)
PY

python3 -m py_compile \
  grantbot/applications/package_builder.py \
  grantbot/api/application_v7.py \
  tests/test_application_v7.py

python3 -m unittest \
  tests.test_application_v7 \
  tests.test_master_v3_v5 \
  -v

python3 -m compileall -q grantbot

python3 -c \
"import grantbot.app; print('GRANTBOT APP IMPORT: OK')"

echo
echo "APPLICATION PACKAGE BUILDER V7 INSTALL COMPLETE"
echo "POST /v7/applications/build"
echo "GET  /v7/applications/{package_id}"
