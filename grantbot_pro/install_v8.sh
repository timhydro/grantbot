#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/grantbot_pro"
source .venv/bin/activate
mkdir -p grantbot/orchestration grantbot/api tests backups data/review_queue
cp grantbot/app.py "backups/app_before_v8_$(date +%Y%m%d_%H%M%S).py"
touch grantbot/orchestration/__init__.py grantbot/api/__init__.py

cat > grantbot/orchestration/application_orchestrator.py <<'PY'
from __future__ import annotations
import json, tempfile, os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from grantbot.applications.package_builder import build_application_package
from grantbot.automation.opportunity_pipeline import Opportunity
from grantbot.discovery.grants_gov import DEFAULT_KEYWORDS, discover

@dataclass(frozen=True, slots=True)
class QueueItem:
    package_id: str
    title: str
    funder: str
    score: int
    priority: str
    readiness_score: int
    status: str
    output_path: str
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".queue_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def run_orchestration(*, keywords: list[str] | None = None, rows_per_keyword: int = 10,
                      minimum_score: int = 80, maximum_packages: int = 10,
                      generate_drafts: bool = True, fetch_details: bool = True) -> dict[str, Any]:
    if not 1 <= rows_per_keyword <= 100: raise ValueError("rows_per_keyword must be 1..100")
    if not 0 <= minimum_score <= 100: raise ValueError("minimum_score must be 0..100")
    if not 1 <= maximum_packages <= 50: raise ValueError("maximum_packages must be 1..50")
    keys = [k.strip() for k in (keywords or DEFAULT_KEYWORDS) if k.strip()]
    d = discover(keywords=keys, rows_per_keyword=rows_per_keyword,
                 fetch_details=fetch_details, generate_drafts=False)
    selected = [x for x in d.results if not x.get("hard_reject") and int(x.get("score",0)) >= minimum_score][:maximum_packages]
    items = []
    for x in selected:
        nofo = x.get("nofo") or {}
        nofo_text = "\n".join([
            str(x.get("title","")), str(x.get("funder","")),
            "\n".join(nofo.get("application_questions",[]) or []),
            "\n".join(nofo.get("requirements",[]) or []),
            "\n".join(nofo.get("priorities",[]) or []),
        ])
        opp = Opportunity(
            id=str(x.get("id","")), title=str(x.get("title","")),
            funder=str(x.get("funder","")), deadline=x.get("deadline"),
            amount=x.get("amount"), source_url=str(x.get("source_url","")),
            nofo_text=nofo_text
        )
        pkg = build_application_package(opp, generate_drafts=generate_drafts)
        items.append(QueueItem(
            pkg.package_id, opp.title, opp.funder, int(x.get("score",0)),
            str(x.get("priority","")), pkg.readiness_score,
            pkg.status, pkg.output_path
        ).to_dict())
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    path = Path(__file__).resolve().parents[2] / "data" / "review_queue" / f"review_queue_{run_id}.json"
    result = {
        "run_id": run_id, "created_at": now.isoformat(), "keywords": keys,
        "discovered_count": d.unique_hits, "selected_count": len(selected),
        "packaged_count": len(items), "queue_path": str(path), "items": items
    }
    _write(path, result)
    return result

def load_latest_queue() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2] / "data" / "review_queue"
    files = sorted(root.glob("review_queue_*.json"), reverse=True)
    if not files: raise FileNotFoundError("No review queue has been created yet.")
    data = json.loads(files[0].read_text(encoding="utf-8"))
    if not isinstance(data, dict): raise RuntimeError("Invalid review queue.")
    return data
PY

cat > grantbot/api/orchestrator_v8.py <<'PY'
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from grantbot.discovery.grants_gov import DEFAULT_KEYWORDS
from grantbot.orchestration.application_orchestrator import run_orchestration, load_latest_queue

router = APIRouter(prefix="/v8/orchestrator", tags=["Application Orchestrator v8"])

class RunRequest(BaseModel):
    keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_KEYWORDS), min_length=1, max_length=25)
    rows_per_keyword: int = Field(default=10, ge=1, le=100)
    minimum_score: int = Field(default=80, ge=0, le=100)
    maximum_packages: int = Field(default=10, ge=1, le=50)
    generate_drafts: bool = True
    fetch_details: bool = True

@router.post("/run")
def run(payload: RunRequest) -> dict[str, Any]:
    try:
        return run_orchestration(**payload.model_dump())
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@router.get("/latest")
def latest() -> dict[str, Any]:
    try:
        return load_latest_queue()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
PY

python3 - <<'PY'
from pathlib import Path
p=Path("grantbot/app.py")
s=p.read_text(encoding="utf-8")
imp="from grantbot.api.orchestrator_v8 import router as orchestrator_v8_router"
reg="app.include_router(orchestrator_v8_router)"
if imp not in s: s += "\n"+imp+"\n"
if reg not in s: s += reg+"\n"
p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile grantbot/orchestration/application_orchestrator.py grantbot/api/orchestrator_v8.py
python3 -m compileall -q grantbot
python3 -c "import grantbot.app; paths=set(grantbot.app.app.openapi().get('paths',{})); assert '/v8/orchestrator/run' in paths and '/v8/orchestrator/latest' in paths, paths; print('V8 ROUTES: OK')" 
echo "V8 INSTALL COMPLETE"
