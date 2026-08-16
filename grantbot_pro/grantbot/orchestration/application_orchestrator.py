from __future__ import annotations
import json, tempfile, os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from grantbot.applications.package_builder import build_application_package
from grantbot.automation.opportunity_pipeline import Opportunity
from grantbot.discovery.grants_gov import DEFAULT_KEYWORDS, discover
from grantbot.nofo.full_detail import get_full_nofo_intelligence

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
        # V9_HARD_GATE_ACTIVE
        opportunity_id = str(x.get("id", "")).strip()
        if not opportunity_id:
            continue
        full_nofo = get_full_nofo_intelligence(opportunity_id)
        gate = full_nofo.eligibility_gate
        if gate.get("decision") == "REJECT":
            continue
        x = dict(x)
        x["v9_nofo"] = full_nofo.to_dict()
        x["score"] = max(
            int(x.get("score", 0)),
            int(full_nofo.analysis.get("fit_score", 0)),
        )
        x["priority"] = full_nofo.analysis.get(
            "priority", x.get("priority", "")
        )
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
