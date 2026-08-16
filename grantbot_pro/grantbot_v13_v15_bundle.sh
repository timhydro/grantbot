#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/grantbot_pro"
cd "$ROOT"

if [[ ! -d ".venv" ]]; then
  echo "ERROR: $ROOT/.venv not found" >&2
  exit 1
fi

source .venv/bin/activate

mkdir -p \
  backups \
  logs \
  tests \
  data/nofo_blueprints \
  data/matching \
  data/compliance \
  grantbot/api \
  grantbot/nofo \
  grantbot/matching \
  grantbot/compliance \
  grantbot/budget \
  grantbot/outcomes

touch \
  grantbot/api/__init__.py \
  grantbot/nofo/__init__.py \
  grantbot/matching/__init__.py \
  grantbot/compliance/__init__.py \
  grantbot/budget/__init__.py \
  grantbot/outcomes/__init__.py

cp grantbot/app.py "backups/app_before_v13_v15_$(date +%Y%m%d_%H%M%S).py"

python3 -m pip install -q "pypdf>=5,<7"

###############################################################################
# V13 — FULL NOFO ACQUISITION + APPLICATION BLUEPRINT
###############################################################################

cat > grantbot/nofo/acquisition_v13.py <<'PY'
from __future__ import annotations

import html
import json
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from grantbot.discovery.grants_gov import fetch_opportunity
from grantbot.nofo.full_detail import get_full_nofo_intelligence


MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024
TIMEOUT_SECONDS = 30
ALLOWED_HOST_SUFFIXES = (".gov", "grants.gov", "simpler.grants.gov")

QUESTION_RE = re.compile(
    r"\b(describe|explain|provide|discuss|identify|demonstrate|summarize|"
    r"detail|outline|justify|address|state|specify|document)\b",
    re.I,
)

REQUIREMENT_RE = re.compile(
    r"\b(must|shall|required|submit|attach|attachment|budget|narrative|"
    r"timeline|work plan|logic model|letter|MOU|MOA|SF-424|UEI|SAM\.gov|"
    r"match|cost[- ]sharing|performance measure|data collection)\b",
    re.I,
)

SCORING_RE = re.compile(
    r"\b(points?|percent|percentage|weighted|weight)\b|\b\d{1,3}\s*%",
    re.I,
)

BUDGET_RE = re.compile(
    r"\b(budget|budget narrative|allowable cost|indirect cost|personnel|"
    r"fringe|travel|equipment|supplies|contractual|construction|other costs?)\b",
    re.I,
)

MATCH_RE = re.compile(
    r"\b(match|matching funds?|cost[- ]sharing|non[- ]federal share|"
    r"in[- ]kind|cash contribution|waiver)\b",
    re.I,
)

SUBMISSION_RE = re.compile(
    r"\b(submit|submission|Grants\.gov|JustGrants|deadline|due date|"
    r"SAM\.gov|UEI|registration|application package)\b",
    re.I,
)

ATTACHMENT_RE = re.compile(
    r"\b(attachment|appendix|letter of support|letter of commitment|"
    r"memorandum of understanding|memorandum of agreement|MOU|MOA|"
    r"logic model|timeline|work plan|budget narrative|project narrative|"
    r"organizational chart|indirect cost rate agreement)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class ApplicationBlueprint:
    opportunity_id: str
    opportunity_number: str
    title: str
    funder: str
    acquisition_status: str
    source_urls: list[str]
    application_questions: list[str]
    requirements: list[str]
    scoring_criteria: list[str]
    budget_requirements: list[str]
    match_requirements: list[str]
    submission_requirements: list[str]
    required_attachments: list[str]
    eligibility: list[str]
    award_ceiling: float | None
    award_floor: float | None
    cost_sharing: bool | None
    warnings: list[str]
    output_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self._ignore = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript", "svg"}:
            self._ignore += 1
        if low == "a":
            for key, value in attrs:
                if key.lower() == "href" and value:
                    self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._ignore:
            self._ignore -= 1

    def handle_data(self, data: str) -> None:
        if self._ignore:
            return
        value = " ".join(data.split()).strip()
        if value:
            self.parts.append(value)


def _safe_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False

    if parsed.scheme != "https":
        return False

    host = (parsed.hostname or "").lower()
    return any(
        host == suffix.lstrip(".") or host.endswith(suffix)
        for suffix in ALLOWED_HOST_SUFFIXES
    )


def _dedupe(values: list[str], limit: int = 300) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for raw in values:
        value = " ".join(str(raw).split()).strip()
        key = value.casefold()

        if not value or key in seen:
            continue

        seen.add(key)
        result.append(value)

        if len(result) >= limit:
            break

    return result


def _walk_strings(value: Any) -> list[str]:
    result: list[str] = []

    if isinstance(value, str):
        result.append(value)
    elif isinstance(value, dict):
        for nested in value.values():
            result.extend(_walk_strings(nested))
    elif isinstance(value, list):
        for nested in value:
            result.extend(_walk_strings(nested))

    return result


def _request(url: str) -> tuple[bytes, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "GrantBotPro/13.0",
            "Accept": "application/pdf,text/html,text/plain,*/*;q=0.2",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    ) as response:
        final_url = response.geturl()

        if not _safe_url(final_url):
            raise ValueError(f"Unsafe redirect: {final_url}")

        content_type = response.headers.get_content_type() or "application/octet-stream"
        data = response.read(MAX_DOWNLOAD_BYTES + 1)

        if len(data) > MAX_DOWNLOAD_BYTES:
            raise ValueError("NOFO document exceeds download size limit")

        return data, content_type, final_url


def _extract_text(
    data: bytes,
    content_type: str,
    url: str,
) -> tuple[str, list[str]]:
    path = urllib.parse.urlparse(url).path.lower()

    if content_type == "application/pdf" or path.endswith(".pdf"):
        reader = PdfReader(BytesIO(data))
        parts: list[str] = []

        for page in reader.pages:
            value = page.extract_text() or ""
            if value.strip():
                parts.append(value)

        return "\n".join(parts), []

    if content_type == "text/html" or path.endswith((".html", ".htm")):
        parser = _HTMLTextParser()
        parser.feed(data.decode("utf-8", errors="replace"))

        links = [
            urllib.parse.urljoin(url, href)
            for href in parser.links
        ]

        return "\n".join(parser.parts), links

    if content_type.startswith("text/") or path.endswith(".txt"):
        return data.decode("utf-8", errors="replace"), []

    return "", []


def _lines(text: str) -> list[str]:
    result: list[str] = []

    for raw in text.replace("\r", "\n").split("\n"):
        value = " ".join(raw.split()).strip()
        if 10 <= len(value) <= 1200:
            result.append(value)

    return result


def _matching(
    lines: list[str],
    pattern: re.Pattern[str],
    limit: int,
) -> list[str]:
    return _dedupe(
        [line for line in lines if pattern.search(line)],
        limit=limit,
    )


def acquire_blueprint(
    opportunity_id: str,
    *,
    manual_urls: list[str] | None = None,
) -> ApplicationBlueprint:
    opportunity_id = opportunity_id.strip()

    if not opportunity_id or len(opportunity_id) > 80:
        raise ValueError("Invalid opportunity_id")

    raw = fetch_opportunity(opportunity_id)

    if not isinstance(raw, dict):
        raise RuntimeError("Invalid Grants.gov opportunity payload")

    full = get_full_nofo_intelligence(opportunity_id)

    urls = [
        f"https://www.grants.gov/search-results-detail/"
        f"{urllib.parse.quote(opportunity_id, safe='')}"
    ]

    for value in _walk_strings(raw):
        value = html.unescape(value.strip())
        if value.startswith("https://") and _safe_url(value):
            urls.append(value)

    for value in manual_urls or []:
        value = value.strip()
        if not _safe_url(value):
            raise ValueError(
                f"Manual NOFO URL must be an HTTPS government source: {value}"
            )
        urls.append(value)

    queue = _dedupe(urls, limit=60)
    visited: set[str] = set()
    acquired_urls: list[str] = []
    text_parts: list[str] = []
    warnings: list[str] = []

    while queue and len(visited) < 40:
        url = queue.pop(0)

        if url in visited or not _safe_url(url):
            continue

        visited.add(url)

        try:
            data, content_type, final_url = _request(url)
            text, links = _extract_text(data, content_type, final_url)

            if text.strip():
                text_parts.append(text)
                acquired_urls.append(final_url)

            for link in links:
                low = link.lower()

                if (
                    _safe_url(link)
                    and any(
                        token in low
                        for token in (
                            ".pdf",
                            "nofo",
                            "notice",
                            "attachment",
                            "download",
                            "instructions",
                        )
                    )
                    and link not in visited
                    and link not in queue
                ):
                    queue.append(link)

        except Exception as exc:
            warnings.append(
                f"{url}: {type(exc).__name__}: {exc}"
            )

    combined = "\n\n".join(text_parts)[:2_000_000]
    lines = _lines(combined)

    questions = _dedupe(
        [
            line
            for line in lines
            if (
                "?" in line
                or QUESTION_RE.search(line)
            )
            and len(line) <= 700
        ],
        limit=250,
    )

    acquisition_status = (
        "FULL_TEXT_ACQUIRED"
        if combined.strip()
        else "METADATA_ONLY"
    )

    if not questions:
        warnings.append(
            "No application questions were extracted from acquired source text."
        )

    root = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "nofo_blueprints"
        / re.sub(r"[^A-Za-z0-9._-]+", "_", opportunity_id)
    )
    root.mkdir(parents=True, exist_ok=True)

    output_path = root / "application_blueprint.json"

    blueprint = ApplicationBlueprint(
        opportunity_id=opportunity_id,
        opportunity_number=full.opportunity_number,
        title=full.title,
        funder=full.funder,
        acquisition_status=acquisition_status,
        source_urls=_dedupe(acquired_urls),
        application_questions=questions,
        requirements=_matching(lines, REQUIREMENT_RE, 350),
        scoring_criteria=_matching(lines, SCORING_RE, 200),
        budget_requirements=_matching(lines, BUDGET_RE, 200),
        match_requirements=_matching(lines, MATCH_RE, 150),
        submission_requirements=_matching(lines, SUBMISSION_RE, 200),
        required_attachments=_matching(lines, ATTACHMENT_RE, 200),
        eligibility=full.eligibility,
        award_ceiling=full.award_ceiling,
        award_floor=full.award_floor,
        cost_sharing=full.cost_sharing,
        warnings=_dedupe(warnings, limit=100),
        output_path=str(output_path),
    )

    output_path.write_text(
        json.dumps(
            blueprint.to_dict(),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    return blueprint


def load_blueprint(opportunity_id: str) -> dict[str, Any]:
    safe_id = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        opportunity_id.strip(),
    )

    path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "nofo_blueprints"
        / safe_id
        / "application_blueprint.json"
    )

    if not path.exists():
        raise FileNotFoundError(str(path))

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise RuntimeError("Stored NOFO blueprint is invalid")

    return data
PY

cat > grantbot/api/nofo_v13.py <<'PY'
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.nofo.acquisition_v13 import (
    acquire_blueprint,
    load_blueprint,
)


router = APIRouter(
    prefix="/v13/nofo",
    tags=["GrantBot NOFO Acquisition v13"],
)


class AcquireRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=80)
    manual_urls: list[str] = Field(default_factory=list, max_length=10)


@router.post("/acquire")
def acquire(payload: AcquireRequest) -> dict[str, Any]:
    try:
        return acquire_blueprint(
            payload.opportunity_id,
            manual_urls=payload.manual_urls,
        ).to_dict()

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{opportunity_id}")
def get_blueprint(opportunity_id: str) -> dict[str, Any]:
    try:
        return load_blueprint(opportunity_id)

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
PY

###############################################################################
# V14 — COMPETITIVE MATCHING + STRENGTH ANALYSIS
###############################################################################

cat > grantbot/matching/competitive_v14.py <<'PY'
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from grantbot.eligibility.applicant_role import classify_applicant_role
from grantbot.nofo.acquisition_v13 import (
    acquire_blueprint,
    load_blueprint,
)
from grantbot.nofo.full_detail import get_full_nofo_intelligence


@dataclass(frozen=True, slots=True)
class CompetitiveMatch:
    opportunity_id: str
    title: str
    funder: str
    applicant_role: dict[str, Any]
    mission_fit_score: int
    readiness_score: int
    competitiveness_score: int
    burden_score: int
    final_score: int
    priority: str
    strengths: list[str]
    weaknesses: list[str]
    blockers: list[str]
    output_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _priority(score: int, blocked: bool) -> str:
    if blocked:
        return "REJECT"
    if score >= 85:
        return "CRITICAL"
    if score >= 75:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    if score >= 40:
        return "LOW"
    return "VERY_LOW"


def analyze_competitiveness(
    opportunity_id: str,
    *,
    acquire_if_missing: bool = True,
) -> CompetitiveMatch:
    full = get_full_nofo_intelligence(opportunity_id)

    role = classify_applicant_role(
        eligibility=full.eligibility,
        existing_blockers=list(
            full.eligibility_gate.get("blockers", [])
        ),
    )

    try:
        blueprint = load_blueprint(opportunity_id)
    except FileNotFoundError:
        if not acquire_if_missing:
            blueprint = {}
        else:
            blueprint = acquire_blueprint(
                opportunity_id
            ).to_dict()

    analysis = full.analysis or {}

    mission_fit = int(
        analysis.get("fit_score", 0)
        or 0
    )

    strengths: list[str] = []
    weaknesses: list[str] = []
    blockers = list(role.blockers)

    questions = blueprint.get("application_questions", [])
    requirements = blueprint.get("requirements", [])
    scoring = blueprint.get("scoring_criteria", [])
    match_requirements = blueprint.get("match_requirements", [])
    attachments = blueprint.get("required_attachments", [])

    readiness = 100

    if not questions:
        readiness -= 20
        weaknesses.append(
            "Application questions are not yet fully extracted."
        )
    else:
        strengths.append(
            "Application questions are available for writer handoff."
        )

    if not requirements:
        readiness -= 15
        weaknesses.append(
            "Application requirements are incomplete."
        )
    else:
        strengths.append(
            "Application requirements have been extracted."
        )

    if not scoring:
        readiness -= 10
        weaknesses.append(
            "Scoring/evaluation criteria are not yet available."
        )
    else:
        strengths.append(
            "Scoring criteria are available for competitive targeting."
        )

    if role.role == "DIRECT_APPLICANT":
        strengths.append(
            "Broken Growth is classified as a direct applicant."
        )
    elif role.role == "PARTNER_OR_SUBRECIPIENT":
        readiness -= 10
        weaknesses.append(
            "Opportunity requires a prime-applicant partnership strategy."
        )
    elif role.role == "VERIFY":
        readiness -= 20
        weaknesses.append(
            "Applicant eligibility requires verification."
        )
    elif role.role == "REJECT":
        blockers.extend(
            role.blockers or ["Opportunity rejected by applicant-role gate."]
        )

    burden = 0

    if full.cost_sharing is True or match_requirements:
        burden += 20
        weaknesses.append(
            "Match/cost-sharing increases application burden."
        )

    if len(attachments) >= 5:
        burden += 10

    if len(requirements) >= 20:
        burden += 10

    readiness = max(0, min(100, readiness))

    competitiveness = round(
        mission_fit * 0.55
        + readiness * 0.45
    )

    final_score = max(
        0,
        min(
            100,
            competitiveness - burden // 2,
        ),
    )

    if blockers:
        final_score = 0

    priority = _priority(
        final_score,
        bool(blockers),
    )

    root = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "matching"
        / str(opportunity_id)
    )
    root.mkdir(parents=True, exist_ok=True)

    output_path = root / "competitive_match.json"

    result = CompetitiveMatch(
        opportunity_id=str(opportunity_id),
        title=full.title,
        funder=full.funder,
        applicant_role=role.to_dict(),
        mission_fit_score=mission_fit,
        readiness_score=readiness,
        competitiveness_score=competitiveness,
        burden_score=burden,
        final_score=final_score,
        priority=priority,
        strengths=list(dict.fromkeys(strengths)),
        weaknesses=list(dict.fromkeys(weaknesses)),
        blockers=list(dict.fromkeys(blockers)),
        output_path=str(output_path),
    )

    output_path.write_text(
        json.dumps(
            result.to_dict(),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    return result
PY

cat > grantbot/api/matching_v14.py <<'PY'
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.matching.competitive_v14 import (
    analyze_competitiveness,
)


router = APIRouter(
    prefix="/v14/matching",
    tags=["GrantBot Competitive Matching v14"],
)


class MatchRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=80)
    acquire_if_missing: bool = True


@router.post("/analyze")
def analyze(payload: MatchRequest) -> dict[str, Any]:
    try:
        return analyze_competitiveness(
            payload.opportunity_id,
            acquire_if_missing=payload.acquire_if_missing,
        ).to_dict()

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
PY

###############################################################################
# V15 — BUDGET + OUTCOMES + COMPLIANCE READINESS
###############################################################################

cat > grantbot/compliance/readiness_v15.py <<'PY'
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from grantbot.matching.competitive_v14 import (
    analyze_competitiveness,
)
from grantbot.nofo.acquisition_v13 import (
    acquire_blueprint,
    load_blueprint,
)


NUMBER_RE = re.compile(
    r"(?<![A-Za-z])(?:\$?\d[\d,]*(?:\.\d+)?%?)(?![A-Za-z])"
)


@dataclass(frozen=True, slots=True)
class ComplianceReadiness:
    opportunity_id: str
    competitive_score: int
    compliance_score: int
    budget_score: int
    outcomes_score: int
    final_readiness_score: int
    status: str
    missing_items: list[str]
    compliance_risks: list[str]
    budget_requirements: list[str]
    outcome_requirements: list[str]
    required_attachments: list[str]
    submission_requirements: list[str]
    output_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _status(score: int, risks: list[str]) -> str:
    if any(
        "REJECT" in risk.upper()
        for risk in risks
    ):
        return "REJECTED"

    if score >= 90:
        return "SUBMISSION_READY"

    if score >= 75:
        return "NEAR_READY"

    if score >= 55:
        return "REVISION_REQUIRED"

    return "NOT_READY"


def evaluate_readiness(
    opportunity_id: str,
) -> ComplianceReadiness:
    competitive = analyze_competitiveness(
        opportunity_id,
        acquire_if_missing=True,
    )

    try:
        blueprint = load_blueprint(opportunity_id)
    except FileNotFoundError:
        blueprint = acquire_blueprint(
            opportunity_id
        ).to_dict()

    missing: list[str] = []
    risks: list[str] = []

    questions = blueprint.get("application_questions", [])
    requirements = blueprint.get("requirements", [])
    budgets = blueprint.get("budget_requirements", [])
    matches = blueprint.get("match_requirements", [])
    attachments = blueprint.get("required_attachments", [])
    submissions = blueprint.get("submission_requirements", [])

    if competitive.priority == "REJECT":
        risks.append(
            "REJECT: opportunity failed competitive/eligibility gate."
        )

    if not questions:
        missing.append(
            "Complete application-question set"
        )

    if not requirements:
        missing.append(
            "Complete application-requirement set"
        )

    if not budgets:
        missing.append(
            "Budget instructions"
        )

    if not submissions:
        missing.append(
            "Submission instructions"
        )

    compliance_score = 100

    if missing:
        compliance_score -= min(
            60,
            len(missing) * 15,
        )

    if competitive.applicant_role.get("verification_required"):
        compliance_score -= 15
        risks.append(
            "Applicant eligibility still requires verification."
        )

    budget_score = 100

    if not budgets:
        budget_score -= 35

    if matches:
        budget_score -= 15
        risks.append(
            "Match/cost-sharing requirements require a verified financing plan."
        )

    outcomes_requirements = [
        line
        for line in requirements
        if any(
            term in line.lower()
            for term in (
                "outcome",
                "performance",
                "measure",
                "evaluation",
                "data collection",
                "reporting",
            )
        )
    ]

    outcomes_score = 100

    if not outcomes_requirements:
        outcomes_score -= 25
        missing.append(
            "Outcome/performance-measure requirements"
        )

    final_score = round(
        competitive.final_score * 0.35
        + compliance_score * 0.30
        + budget_score * 0.20
        + outcomes_score * 0.15
    )

    final_score = max(
        0,
        min(100, final_score),
    )

    status = _status(
        final_score,
        risks,
    )

    root = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "compliance"
        / str(opportunity_id)
    )
    root.mkdir(parents=True, exist_ok=True)

    output_path = root / "readiness_v15.json"

    result = ComplianceReadiness(
        opportunity_id=str(opportunity_id),
        competitive_score=competitive.final_score,
        compliance_score=max(0, compliance_score),
        budget_score=max(0, budget_score),
        outcomes_score=max(0, outcomes_score),
        final_readiness_score=final_score,
        status=status,
        missing_items=list(dict.fromkeys(missing)),
        compliance_risks=list(dict.fromkeys(risks)),
        budget_requirements=budgets,
        outcome_requirements=outcomes_requirements,
        required_attachments=attachments,
        submission_requirements=submissions,
        output_path=str(output_path),
    )

    output_path.write_text(
        json.dumps(
            result.to_dict(),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    return result
PY

cat > grantbot/api/readiness_v15.py <<'PY'
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grantbot.compliance.readiness_v15 import (
    evaluate_readiness,
)


router = APIRouter(
    prefix="/v15/readiness",
    tags=["GrantBot Budget Outcomes Compliance v15"],
)


class ReadinessRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=80)


@router.post("/evaluate")
def evaluate(payload: ReadinessRequest) -> dict[str, Any]:
    try:
        return evaluate_readiness(
            payload.opportunity_id
        ).to_dict()

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
PY

###############################################################################
# TESTS
###############################################################################

cat > tests/test_v13_v15_bundle.py <<'PY'
from __future__ import annotations

import unittest

from grantbot.nofo.acquisition_v13 import (
    _dedupe,
    _lines,
    _safe_url,
)
from grantbot.matching.competitive_v14 import _priority
from grantbot.compliance.readiness_v15 import _status


class V13V15BundleTests(unittest.TestCase):
    def test_safe_government_urls(self) -> None:
        self.assertTrue(
            _safe_url("https://www.grants.gov/test.pdf")
        )
        self.assertTrue(
            _safe_url("https://www.ojp.gov/test.pdf")
        )
        self.assertFalse(
            _safe_url("http://www.grants.gov/test.pdf")
        )
        self.assertFalse(
            _safe_url("https://example.com/test.pdf")
        )

    def test_dedupe(self) -> None:
        self.assertEqual(
            _dedupe(["A", "A", "B"]),
            ["A", "B"],
        )

    def test_line_normalization(self) -> None:
        lines = _lines(
            "Describe the proposed program and implementation strategy.\n"
            "Short\n"
            "Provide a complete budget narrative."
        )
        self.assertEqual(len(lines), 2)

    def test_priority(self) -> None:
        self.assertEqual(
            _priority(90, False),
            "CRITICAL",
        )
        self.assertEqual(
            _priority(90, True),
            "REJECT",
        )

    def test_status(self) -> None:
        self.assertEqual(
            _status(95, []),
            "SUBMISSION_READY",
        )
        self.assertEqual(
            _status(40, []),
            "NOT_READY",
        )
        self.assertEqual(
            _status(
                95,
                ["REJECT: failed gate"],
            ),
            "REJECTED",
        )


if __name__ == "__main__":
    unittest.main()
PY

###############################################################################
# REGISTER ROUTERS
###############################################################################

python3 - <<'PY'
from pathlib import Path

p = Path("grantbot/app.py")
s = p.read_text(encoding="utf-8")

routers = (
    (
        "from grantbot.api.nofo_v13 import router as nofo_v13_router",
        "app.include_router(nofo_v13_router)",
    ),
    (
        "from grantbot.api.matching_v14 import router as matching_v14_router",
        "app.include_router(matching_v14_router)",
    ),
    (
        "from grantbot.api.readiness_v15 import router as readiness_v15_router",
        "app.include_router(readiness_v15_router)",
    ),
)

for imp, reg in routers:
    if imp not in s:
        s += "\n" + imp + "\n"
    if reg not in s:
        s += reg + "\n"

p.write_text(
    s,
    encoding="utf-8",
)

print("V13-V15 ROUTERS REGISTERED")
PY

###############################################################################
# VERIFY
###############################################################################

python3 -m py_compile \
  grantbot/nofo/acquisition_v13.py \
  grantbot/api/nofo_v13.py \
  grantbot/matching/competitive_v14.py \
  grantbot/api/matching_v14.py \
  grantbot/compliance/readiness_v15.py \
  grantbot/api/readiness_v15.py \
  tests/test_v13_v15_bundle.py \
  grantbot/app.py

python3 -m unittest tests.test_v13_v15_bundle -v
python3 -m compileall -q grantbot

python3 - <<'PY'
import grantbot.app

paths = set(
    grantbot.app.app.openapi().get(
        "paths",
        {},
    )
)

required = {
    "/v13/nofo/acquire",
    "/v13/nofo/{opportunity_id}",
    "/v14/matching/analyze",
    "/v15/readiness/evaluate",
}

missing = required - paths

if missing:
    raise SystemExit(
        f"ERROR: Missing routes: {sorted(missing)}"
    )

print("V13-V15 IMPORT + ROUTES: OK")
PY

pkill -f '[u]vicorn.*grantbot.app:app' 2>/dev/null || true
sleep 2

nohup "$ROOT/.venv/bin/python3" \
  -m uvicorn grantbot.app:app \
  --host 127.0.0.1 \
  --port 8000 \
  > "$ROOT/logs/uvicorn.log" 2>&1 &

for _ in $(seq 1 20); do
  if curl -fsS \
    http://127.0.0.1:8000/openapi.json \
    >/dev/null 2>&1
  then
    break
  fi
  sleep 1
done

curl -fsS \
  http://127.0.0.1:8000/openapi.json \
  >/dev/null

echo "============================================================"
echo " GRANTBOT V13-V15 MASTER BUNDLE INSTALLED"
echo "============================================================"
echo "POST /v13/nofo/acquire"
echo "GET  /v13/nofo/{opportunity_id}"
echo "POST /v14/matching/analyze"
echo "POST /v15/readiness/evaluate"
echo "============================================================"
