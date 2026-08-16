#!/usr/bin/env bash
set -euo pipefail
ROOT="$HOME/grantbot_pro"
cd "$ROOT"
source .venv/bin/activate
mkdir -p grantbot/partners grantbot/api data/partner_packages logs backups
touch grantbot/partners/__init__.py grantbot/api/__init__.py
cp grantbot/app.py "backups/app_before_v12_$(date +%Y%m%d_%H%M%S).py"

cat > grantbot/partners/package_builder.py <<'PY'
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
PY

cat > grantbot/api/partners_v12.py <<'PY'
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from grantbot.partners.package_builder import build_partner_package, load_partner_package

router = APIRouter(prefix="/v12/partners", tags=["GrantBot Partner Action Engine v12"])

class BuildRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=50)

@router.post("/build")
def build(payload: BuildRequest) -> dict[str, Any]:
    try:
        return build_partner_package(payload.opportunity_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get("/{opportunity_id}")
def get_package(opportunity_id: str) -> dict[str, Any]:
    try:
        return load_partner_package(opportunity_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
PY

python3 - <<'PY'
from pathlib import Path
p = Path("grantbot/app.py")
s = p.read_text(encoding="utf-8")
imp = "from grantbot.api.partners_v12 import router as partners_v12_router"
reg = "app.include_router(partners_v12_router)"
if imp not in s:
    s += "\n" + imp + "\n"
if reg not in s:
    s += reg + "\n"
p.write_text(s, encoding="utf-8")
print("V12 ROUTER REGISTERED")
PY

python3 -m py_compile grantbot/partners/package_builder.py grantbot/api/partners_v12.py grantbot/app.py
python3 -m compileall -q grantbot
python3 -c 'import grantbot.app; paths=set(grantbot.app.app.openapi().get("paths",{})); assert "/v12/partners/build" in paths; print("V12 IMPORT OK")'
pkill -f '[u]vicorn.*grantbot.app:app' 2>/dev/null || true
sleep 2
nohup "$ROOT/.venv/bin/python3" -m uvicorn grantbot.app:app --host 127.0.0.1 --port 8000 > "$ROOT/logs/uvicorn.log" 2>&1 &
for _ in $(seq 1 20); do
  curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:8000/openapi.json | grep -q '"/v12/partners/build"'
echo "V12 LIVE ROUTE OK"
curl -fsS -X POST http://127.0.0.1:8000/v12/partners/build -H 'Content-Type: application/json' -d '{"opportunity_id":"363588"}' > data/partner_packages/v12_build_result.json
python3 -m json.tool data/partner_packages/v12_build_result.json
test -f data/partner_packages/363588/partner_package.json
test -f data/partner_packages/363588/concept_summary.md
test -f data/partner_packages/363588/scope_of_work.md
test -f data/partner_packages/363588/outreach_pitch.md
echo "V12 PACKAGE 363588 CREATED"
