#!/usr/bin/env bash
set -Eeuo pipefail

find_root() {
  if [[ -n "${GRANTBOT_ROOT:-}" && -f "$GRANTBOT_ROOT/grantbot/app.py" ]]; then printf "%s\n" "$GRANTBOT_ROOT"; return; fi
  if [[ -f "$HOME/grantbot_pro/grantbot/app.py" ]]; then printf "%s\n" "$HOME/grantbot_pro"; return; fi
  local c; c="$(find "$HOME" -maxdepth 5 -type f -path "*/grantbot/app.py" -print -quit 2>/dev/null || true)"
  [[ -n "$c" ]] || { echo "ERROR: Could not locate grantbot/app.py" >&2; exit 1; }
  dirname "$(dirname "$c")"
}

ROOT="$(find_root)"
cd "$ROOT"
if [[ -x .venv/bin/python ]]; then PY="$ROOT/.venv/bin/python"; elif [[ -x venv/bin/python ]]; then PY="$ROOT/venv/bin/python"; else echo "ERROR: No .venv or venv found" >&2; exit 1; fi
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p backups logs data grantbot/master grantbot/api tests .github/workflows
cp grantbot/app.py "backups/app_before_master_${STAMP}.py"
if [[ -f data/grantbot.db ]]; then cp data/grantbot.db "backups/grantbot_before_master_${STAMP}.db"; fi
MISSING_DEPS="$($PY - <<'PY_DEPS'
mods = {"fastapi":"fastapi>=0.115,<1","uvicorn":"uvicorn>=0.30,<1","pydantic":"pydantic>=2.8,<3","multipart":"python-multipart>=0.0.9,<1","pypdf":"pypdf>=5,<7"}
missing=[]
for module, spec in mods.items():
    try: __import__(module)
    except ImportError: missing.append(spec)
print(" ".join(missing))
PY_DEPS
)"
if [[ -n "$MISSING_DEPS" ]]; then
  "$PY" -m pip install $MISSING_DEPS
else
  echo "MASTER DEPENDENCIES: ALREADY PRESENT"
fi

mkdir -p "$(dirname 'grantbot/master/__init__.py')"
cat > 'grantbot/master/__init__.py' <<'GBM_GRANTBOT_MASTER___INIT___PY'
from .service import MasterService

__all__ = ["MasterService"]
GBM_GRANTBOT_MASTER___INIT___PY

mkdir -p "$(dirname 'grantbot/master/db.py')"
cat > 'grantbot/master/db.py' <<'GBM_GRANTBOT_MASTER_DB_PY'
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def root() -> Path:
    configured = os.getenv("GRANTBOT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def db_path() -> Path:
    configured = os.getenv("GRANTBOT_DB_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else root() / "data" / "grantbot.db"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS gbm_schema_migrations(
  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gbm_facts(
  fact_id TEXT PRIMARY KEY, fact_key TEXT NOT NULL, category TEXT NOT NULL,
  value_json TEXT NOT NULL, fact_type TEXT NOT NULL, verification_state TEXT NOT NULL,
  source_type TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL,
  valid_from TEXT NOT NULL, valid_to TEXT, collected_at TEXT NOT NULL, verified_at TEXT,
  supersedes_fact_id TEXT, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gbm_facts_key_current ON gbm_facts(fact_key, valid_to, created_at DESC);
CREATE TABLE IF NOT EXISTS gbm_documents(
  document_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL DEFAULT '', source_uri TEXT NOT NULL,
  sha256 TEXT NOT NULL, document_type TEXT NOT NULL, authority TEXT NOT NULL, authority_rank INTEGER NOT NULL,
  publication_date TEXT, fiscal_year TEXT, is_primary INTEGER NOT NULL, stored_path TEXT NOT NULL,
  text_path TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gbm_docs_opp ON gbm_documents(opportunity_id, authority_rank);
CREATE TABLE IF NOT EXISTS gbm_requirements(
  requirement_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, document_id TEXT NOT NULL,
  requirement_type TEXT NOT NULL, category TEXT NOT NULL, requirement_text TEXT NOT NULL,
  page_number INTEGER, section TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL,
  authority_rank INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'UNRESOLVED', evidence_json TEXT NOT NULL DEFAULT '{}',
  extracted_at TEXT NOT NULL, FOREIGN KEY(document_id) REFERENCES gbm_documents(document_id)
);
CREATE INDEX IF NOT EXISTS idx_gbm_req_opp ON gbm_requirements(opportunity_id, category, authority_rank);
CREATE TABLE IF NOT EXISTS gbm_opportunities(
  opportunity_id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL, funder TEXT NOT NULL,
  deadline TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, score_json TEXT NOT NULL, raw_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gbm_applications(
  application_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL DEFAULT '',
  stage TEXT NOT NULL, requested_amount REAL, match_amount REAL, human_approved INTEGER NOT NULL DEFAULT 0,
  approved_by TEXT NOT NULL DEFAULT '', approved_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gbm_draft_revisions(
  revision_id TEXT PRIMARY KEY, application_id TEXT NOT NULL, task_key TEXT NOT NULL, revision_number INTEGER NOT NULL,
  section_type TEXT NOT NULL, funder_archetype TEXT NOT NULL, question TEXT NOT NULL, text TEXT NOT NULL,
  model TEXT NOT NULL, prompt_hash TEXT NOT NULL, evidence_json TEXT NOT NULL, quality_json TEXT NOT NULL,
  status TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(application_id, task_key, revision_number), FOREIGN KEY(application_id) REFERENCES gbm_applications(application_id)
);
CREATE INDEX IF NOT EXISTS idx_gbm_rev_current ON gbm_draft_revisions(application_id, task_key, revision_number DESC);
CREATE TABLE IF NOT EXISTS gbm_claim_checks(
  claim_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, sentence TEXT NOT NULL, support_fact_ids_json TEXT NOT NULL,
  support_score REAL NOT NULL, numeric_supported INTEGER NOT NULL, language_valid INTEGER NOT NULL,
  issues_json TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(revision_id) REFERENCES gbm_draft_revisions(revision_id)
);
CREATE TABLE IF NOT EXISTS gbm_feedback(
  feedback_id TEXT PRIMARY KEY, application_id TEXT NOT NULL, task_key TEXT NOT NULL, section_type TEXT NOT NULL,
  funder_archetype TEXT NOT NULL, before_text TEXT NOT NULL, after_text TEXT NOT NULL, accepted INTEGER NOT NULL,
  edit_tags_json TEXT NOT NULL, reviewer TEXT NOT NULL, reviewer_score REAL, outcome TEXT NOT NULL DEFAULT '',
  award_amount REAL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gbm_feedback_lookup ON gbm_feedback(section_type, funder_archetype, accepted);
CREATE TABLE IF NOT EXISTS gbm_budgets(
  budget_id TEXT PRIMARY KEY, application_id TEXT NOT NULL, payload_json TEXT NOT NULL, totals_json TEXT NOT NULL,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gbm_logic_models(
  logic_id TEXT PRIMARY KEY, application_id TEXT NOT NULL, payload_json TEXT NOT NULL, validation_json TEXT NOT NULL,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gbm_consistency_checks(
  check_id TEXT PRIMARY KEY, application_id TEXT NOT NULL, category TEXT NOT NULL, passed INTEGER NOT NULL,
  message TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gbm_users(
  user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, key_salt TEXT NOT NULL, key_hash TEXT NOT NULL,
  roles_json TEXT NOT NULL, enabled INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gbm_audit(
  event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, actor TEXT NOT NULL, entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gbm_audit_entity ON gbm_audit(entity_type, entity_id, created_at DESC);
CREATE TABLE IF NOT EXISTS gbm_deadlines(
  deadline_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, application_id TEXT NOT NULL DEFAULT '',
  due_at TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gbm_jobs(
  job_id TEXT PRIMARY KEY, job_type TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL,
  attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL, run_after TEXT NOT NULL, locked_at TEXT NOT NULL DEFAULT '',
  last_error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gbm_jobs_due ON gbm_jobs(status, run_after);
CREATE TABLE IF NOT EXISTS gbm_uploads(
  upload_id TEXT PRIMARY KEY, application_id TEXT NOT NULL DEFAULT '', original_name TEXT NOT NULL,
  stored_path TEXT NOT NULL, mime_type TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
  page_count INTEGER, status TEXT NOT NULL, approved_by TEXT NOT NULL DEFAULT '', approved_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gbm_embeddings(
  entity_key TEXT NOT NULL, content_hash TEXT NOT NULL, model TEXT NOT NULL, vector_json TEXT NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY(entity_key, content_hash, model)
);
"""


def migrate() -> dict[str, Any]:
    with connect() as conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT 1 FROM gbm_schema_migrations WHERE version=1").fetchone()
        if row is None:
            conn.execute("INSERT INTO gbm_schema_migrations(version,name,applied_at) VALUES(1,?,?)", ("GrantBot Master canonical schema", utc_now()))
    imported = import_legacy()
    return {"database": str(db_path()), "schema_version": 1, "legacy_import": imported}


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def columns(conn: sqlite3.Connection, name: str) -> set[str]:
    if not table_exists(conn, name):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({name})")}


def audit(event_type: str, actor: str, entity_type: str, entity_id: str, payload: dict[str, Any] | None = None) -> str:
    event_id = f"evt_{uuid.uuid4().hex}"
    with connect() as conn:
        conn.execute(
            "INSERT INTO gbm_audit(event_id,event_type,actor,entity_type,entity_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (event_id, event_type, actor, entity_type, entity_id, json.dumps(payload or {}, ensure_ascii=False, default=str), utc_now()),
        )
    return event_id


def import_legacy() -> dict[str, int]:
    counts = {"facts": 0, "applications": 0, "revisions": 0, "events": 0}
    with connect() as conn:
        if table_exists(conn, "facts") and {"fact_key", "value"}.issubset(columns(conn, "facts")):
            for row in conn.execute("SELECT * FROM facts"):
                data = dict(row); key = str(data.get("fact_key") or "").strip()
                if not key: continue
                exists = conn.execute("SELECT 1 FROM gbm_facts WHERE fact_key=? AND source_ref='legacy:facts'", (key,)).fetchone()
                if exists: continue
                status = str(data.get("status") or "UNVERIFIED").upper()
                state = "VERIFIED" if status in {"VERIFIED","APPROVED"} else ("MISSING" if "MISSING" in status else "UNVERIFIED")
                now = utc_now(); fid = f"fact_{uuid.uuid4().hex}"
                conn.execute("INSERT INTO gbm_facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    fid, key, str(data.get("category") or "general"), json.dumps(data.get("value"), ensure_ascii=False, default=str),
                    "USER_PROVIDED_FACT", state, "LEGACY_DATABASE", "legacy:facts", 1.0 if state=="VERIFIED" else 0.5,
                    now, None, now, now if state=="VERIFIED" else None, None, "Imported from legacy facts table", now))
                counts["facts"] += 1
        if table_exists(conn, "application_staging_v17"):
            for row in conn.execute("SELECT * FROM application_staging_v17"):
                d=dict(row); app_id=f"app_{d['workspace_id']}"
                conn.execute("INSERT OR IGNORE INTO gbm_applications(application_id,opportunity_id,title,stage,requested_amount,match_amount,human_approved,approved_by,approved_at,created_at,updated_at) VALUES(?,?,?,?,NULL,NULL,?,?,?,?,?)",
                    (app_id,str(d['opportunity_id']),str(d['title']),str(d['stage']),int(d['human_approved']),str(d['approved_by']),str(d['approved_at']),str(d['created_at']),str(d['updated_at'])))
                counts["applications"] += conn.execute("SELECT changes()").fetchone()[0]
        if table_exists(conn, "application_drafts_v17"):
            for row in conn.execute("SELECT * FROM application_drafts_v17 WHERE response<>''"):
                d=dict(row); app_id=f"app_{d['workspace_id']}"; task=str(d['task_id']); rev=int(d['version'])
                rid=f"legacy17_{task}_{rev}"
                conn.execute("INSERT OR IGNORE INTO gbm_draft_revisions(revision_id,application_id,task_key,revision_number,section_type,funder_archetype,question,text,model,prompt_hash,evidence_json,quality_json,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid,app_id,task,rev,str(d['category']),"unknown",str(d['question']),str(d['response']),"legacy-v17","legacy",str(d['provenance_json']),"{}",str(d['status']),"legacy-import",str(d['updated_at'])))
                counts["revisions"] += conn.execute("SELECT changes()").fetchone()[0]
        if table_exists(conn, "application_review_events_v17"):
            for row in conn.execute("SELECT * FROM application_review_events_v17"):
                d=dict(row); eid=f"legacy17_{d['event_id']}"
                conn.execute("INSERT OR IGNORE INTO gbm_audit(event_id,event_type,actor,entity_type,entity_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (eid,str(d['event_type']),str(d['actor']),"application",f"app_{d['workspace_id']}",json.dumps({"from":d['from_stage'],"to":d['to_stage'],"note":d['note']}),str(d['created_at'])))
                counts["events"] += conn.execute("SELECT changes()").fetchone()[0]
    return counts


def health() -> dict[str, Any]:
    migrate()
    required={"gbm_facts","gbm_documents","gbm_requirements","gbm_applications","gbm_draft_revisions","gbm_feedback","gbm_users","gbm_audit"}
    with connect() as conn:
        tables={str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        migration=conn.execute("SELECT MAX(version) FROM gbm_schema_migrations").fetchone()[0]
    return {"healthy": required.issubset(tables), "schema_version": int(migration or 0), "database": str(db_path()), "tables_ready": sorted(required & tables)}
GBM_GRANTBOT_MASTER_DB_PY

mkdir -p "$(dirname 'grantbot/master/security.py')"
cat > 'grantbot/master/security.py' <<'GBM_GRANTBOT_MASTER_SECURITY_PY'
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from fastapi import Header, HTTPException

from .db import connect, migrate, root, utc_now

PBKDF2_ROUNDS = 240_000
DEFAULT_ROLES = ["ADMIN", "GRANT_WRITER", "REVIEWER", "FINANCIAL_REVIEWER", "AUTHORIZED_REPRESENTATIVE"]

@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    display_name: str
    roles: frozenset[str]


def _derive(secret: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, PBKDF2_ROUNDS).hex()


def key_file() -> Path:
    return root() / "data" / "master_api_key.txt"


def ensure_bootstrap_admin() -> dict[str, str]:
    migrate(); user_id="admin"
    with connect() as conn:
        row=conn.execute("SELECT user_id FROM gbm_users WHERE user_id=?",(user_id,)).fetchone()
        if row is not None:
            return {"user_id":user_id,"key_file":str(key_file()),"created":"false"}
        secret=secrets.token_urlsafe(36); salt=secrets.token_bytes(24); now=utc_now()
        conn.execute("INSERT INTO gbm_users(user_id,display_name,key_salt,key_hash,roles_json,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (user_id,"GrantBot Administrator",salt.hex(),_derive(secret,salt),json.dumps(DEFAULT_ROLES),1,now,now))
    full=f"{user_id}.{secret}"; p=key_file(); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(full+"\n",encoding="utf-8"); os.chmod(p,0o600)
    return {"user_id":user_id,"key_file":str(p),"created":"true"}


def authenticate(api_key: str) -> UserContext:
    if "." not in api_key: raise HTTPException(status_code=401,detail="Invalid API key")
    user_id,secret=api_key.split(".",1)
    with connect() as conn:
        row=conn.execute("SELECT * FROM gbm_users WHERE user_id=? AND enabled=1",(user_id,)).fetchone()
    if row is None: raise HTTPException(status_code=401,detail="Invalid API key")
    expected=_derive(secret,bytes.fromhex(str(row["key_salt"])))
    if not hmac.compare_digest(expected,str(row["key_hash"])): raise HTTPException(status_code=401,detail="Invalid API key")
    return UserContext(user_id=user_id,display_name=str(row["display_name"]),roles=frozenset(json.loads(str(row["roles_json"]))))


def current_user(x_grantbot_key: str | None = Header(default=None, alias="X-GrantBot-Key")) -> UserContext:
    if not x_grantbot_key: raise HTTPException(status_code=401,detail="X-GrantBot-Key header is required")
    return authenticate(x_grantbot_key)


def require(user: UserContext, roles: Iterable[str]) -> None:
    wanted=set(roles)
    if not user.roles.intersection(wanted): raise HTTPException(status_code=403,detail=f"Required role: {sorted(wanted)}")
GBM_GRANTBOT_MASTER_SECURITY_PY

mkdir -p "$(dirname 'grantbot/master/knowledge.py')"
cat > 'grantbot/master/knowledge.py' <<'GBM_GRANTBOT_MASTER_KNOWLEDGE_PY'
from __future__ import annotations

import json
import uuid
from typing import Any

from .db import audit, connect, migrate, utc_now

FACT_TYPES={"VERIFIED_FACT","USER_PROVIDED_FACT","CALCULATED_VALUE","EXTERNAL_SOURCE","REASONABLE_PROJECTION","UNVERIFIED_CLAIM","MISSING_INFORMATION"}
STATES={"VERIFIED","APPROVED","UNVERIFIED","MISSING","SUPERSEDED","EXPIRED"}


def set_fact(*,fact_key:str,category:str,value:Any,fact_type:str,verification_state:str,source_type:str,source_ref:str="",confidence:float=1.0,notes:str="",actor:str="system") -> dict[str,Any]:
    migrate(); fact_key=fact_key.strip(); category=category.strip() or "general"; ft=fact_type.upper(); state=verification_state.upper()
    if not fact_key: raise ValueError("fact_key is required")
    if ft not in FACT_TYPES: raise ValueError(f"Invalid fact_type: {ft}")
    if state not in STATES: raise ValueError(f"Invalid verification_state: {state}")
    if not 0<=float(confidence)<=1: raise ValueError("confidence must be 0..1")
    now=utc_now(); fid=f"fact_{uuid.uuid4().hex}"; previous=None
    with connect() as conn:
        row=conn.execute("SELECT fact_id FROM gbm_facts WHERE fact_key=? AND valid_to IS NULL ORDER BY created_at DESC LIMIT 1",(fact_key,)).fetchone()
        if row:
            previous=str(row["fact_id"]); conn.execute("UPDATE gbm_facts SET valid_to=? WHERE fact_id=?",(now,previous))
        conn.execute("INSERT INTO gbm_facts(fact_id,fact_key,category,value_json,fact_type,verification_state,source_type,source_ref,confidence,valid_from,valid_to,collected_at,verified_at,supersedes_fact_id,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid,fact_key,category,json.dumps(value,ensure_ascii=False,default=str),ft,state,source_type,source_ref,float(confidence),now,None,now,now if state in {"VERIFIED","APPROVED"} else None,previous,notes,now))
    audit("FACT_SET",actor,"fact",fid,{"fact_key":fact_key,"supersedes":previous})
    return get_fact(fact_key) or {}


def _row(row:Any)->dict[str,Any]:
    d=dict(row); d["value"]=json.loads(str(d.pop("value_json"))); return d


def get_fact(fact_key:str)->dict[str,Any]|None:
    migrate()
    with connect() as conn: row=conn.execute("SELECT * FROM gbm_facts WHERE fact_key=? AND valid_to IS NULL ORDER BY created_at DESC LIMIT 1",(fact_key,)).fetchone()
    return _row(row) if row else None


def list_facts(*,states:list[str]|None=None,category:str|None=None)->list[dict[str,Any]]:
    migrate(); sql="SELECT * FROM gbm_facts WHERE valid_to IS NULL"; args:list[Any]=[]
    if states:
        marks=','.join('?' for _ in states); sql+=f" AND verification_state IN ({marks})"; args.extend(s.upper() for s in states)
    if category: sql+=" AND category=?"; args.append(category)
    sql+=" ORDER BY category,fact_key"
    with connect() as conn: rows=conn.execute(sql,args).fetchall()
    return [_row(r) for r in rows]


def conflicts()->list[dict[str,Any]]:
    migrate(); out=[]
    with connect() as conn:
        keys=conn.execute("SELECT fact_key,COUNT(*) c FROM gbm_facts WHERE valid_to IS NULL GROUP BY fact_key HAVING c>1").fetchall()
        for k in keys:
            rows=conn.execute("SELECT * FROM gbm_facts WHERE fact_key=? AND valid_to IS NULL",(k["fact_key"],)).fetchall(); vals={str(r["value_json"]) for r in rows}
            if len(vals)>1: out.append({"fact_key":k["fact_key"],"versions":[_row(r) for r in rows]})
    return out
GBM_GRANTBOT_MASTER_KNOWLEDGE_PY

mkdir -p "$(dirname 'grantbot/master/intelligence.py')"
cat > 'grantbot/master/intelligence.py' <<'GBM_GRANTBOT_MASTER_INTELLIGENCE_PY'
from __future__ import annotations

import hashlib
import html
import json
import math
import mimetypes
import os
import re
import shutil
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import audit, connect, migrate, root, utc_now
from .knowledge import list_facts

AUTHORITY_RANK={"PRIMARY_NOFO":1,"AMENDMENT":2,"APPLICATION_INSTRUCTIONS":3,"OFFICIAL_FORM":4,"OFFICIAL_FAQ":5,"OFFICIAL_GUIDANCE":6,"WEBINAR_TRANSCRIPT":7,"INFORMATIONAL_WEBPAGE":8,"OTHER":9}
MANDATORY_WORDS=re.compile(r"\b(must|required|shall|is required to|are required to)\b",re.I)
CONDITIONAL_WORDS=re.compile(r"\b(if|when|where applicable|as applicable|if applicable|conditional)\b",re.I)
ATTACHMENT_WORDS=re.compile(r"\b(attachment|appendix|form|sf[- ]?424|budget narrative|letter of support|resume|vitae|certification|assurances?)\b",re.I)
MATCH_WORDS=re.compile(r"\b(match|cost[- ]?share|non[- ]?federal share|leveraged funds?)\b",re.I)
ELIGIBILITY_WORDS=re.compile(r"\b(eligible|eligibility|applicant|nonprofit|501\(c\)\(3\)|government|local government|state|tribal|institution)\b",re.I)
DEADLINE_WORDS=re.compile(r"\b(deadline|due date|submit(?:ted)? by|closing date)\b",re.I)
LIMIT_WORDS=re.compile(r"\b(page limit|pages|word limit|words|character limit|characters)\b",re.I)
AWARD_WORDS=re.compile(r"\b(award|funding amount|ceiling|floor|minimum|maximum|request amount)\b",re.I)


def _sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def _strip_html(text:str)->str:
    text=re.sub(r"(?is)<(script|style).*?>.*?</\1>"," ",text); text=re.sub(r"(?s)<[^>]+>"," ",text); return html.unescape(re.sub(r"\s+"," ",text)).strip()


def ingest_file(path:str,*,opportunity_id:str="",source_uri:str="",document_type:str="NOFO",authority:str="PRIMARY_NOFO",publication_date:str|None=None,fiscal_year:str|None=None,is_primary:bool=True,actor:str="system")->dict[str,Any]:
    migrate(); src=Path(path).expanduser().resolve()
    if not src.is_file(): raise FileNotFoundError(str(src))
    if src.stat().st_size>50*1024*1024: raise ValueError("Document exceeds 50 MB limit")
    auth=authority.upper(); rank=AUTHORITY_RANK.get(auth,9); did=f"doc_{uuid.uuid4().hex}"; ddir=root()/"data"/"master_documents"/did; ddir.mkdir(parents=True,exist_ok=True)
    stored=ddir/src.name; shutil.copy2(src,stored); suffix=src.suffix.lower(); pages:list[str]=[]
    if suffix=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(str(stored)); pages=[(p.extract_text() or "") for p in reader.pages]
    elif suffix in {'.txt','.md','.csv','.json','.xml'}: pages=[stored.read_text(encoding='utf-8',errors='replace')]
    elif suffix in {'.html','.htm'}: pages=[_strip_html(stored.read_text(encoding='utf-8',errors='replace'))]
    else: raise ValueError(f"Unsupported document format: {suffix}")
    text_path=ddir/'extracted.txt'; text_path.write_text('\n\n'.join(f"=== PAGE {i+1} ===\n{t}" for i,t in enumerate(pages)),encoding='utf-8')
    meta={"pages":len(pages),"original_name":src.name,"mime_type":mimetypes.guess_type(src.name)[0] or 'application/octet-stream'}
    with connect() as conn:
        conn.execute("INSERT INTO gbm_documents(document_id,opportunity_id,source_uri,sha256,document_type,authority,authority_rank,publication_date,fiscal_year,is_primary,stored_path,text_path,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (did,opportunity_id,source_uri or str(src),_sha(stored),document_type,auth,rank,publication_date,fiscal_year,1 if is_primary else 0,str(stored),str(text_path),json.dumps(meta),utc_now()))
    reqs=extract_requirements(did,pages); audit("DOCUMENT_INGESTED",actor,"document",did,{"requirements":len(reqs),"authority":auth})
    return {"document_id":did,"stored_path":str(stored),"text_path":str(text_path),"metadata":meta,"requirements":reqs}


def ingest_text(text:str,*,opportunity_id:str,source_uri:str,document_type:str="NOFO",authority:str="PRIMARY_NOFO",actor:str="system")->dict[str,Any]:
    if not text.strip(): raise ValueError("text is required")
    tmp=root()/"data"/"master_ingest"/f"{uuid.uuid4().hex}.txt"; tmp.parent.mkdir(parents=True,exist_ok=True); tmp.write_text(text,encoding='utf-8')
    try: return ingest_file(str(tmp),opportunity_id=opportunity_id,source_uri=source_uri,document_type=document_type,authority=authority,actor=actor)
    finally: tmp.unlink(missing_ok=True)


def _classify(line:str)->str:
    if ATTACHMENT_WORDS.search(line): return "ATTACHMENT"
    if MATCH_WORDS.search(line): return "MATCH"
    if ELIGIBILITY_WORDS.search(line): return "ELIGIBILITY"
    if DEADLINE_WORDS.search(line): return "DEADLINE"
    if LIMIT_WORDS.search(line): return "FORMAT_LIMIT"
    if AWARD_WORDS.search(line): return "AWARD"
    return "GENERAL_REQUIREMENT"


def extract_requirements(document_id:str,pages:list[str]|None=None)->list[dict[str,Any]]:
    migrate()
    with connect() as conn: doc=conn.execute("SELECT * FROM gbm_documents WHERE document_id=?",(document_id,)).fetchone()
    if doc is None: raise FileNotFoundError(document_id)
    if pages is None:
        raw=Path(str(doc['text_path'])).read_text(encoding='utf-8',errors='replace'); pages=re.split(r"=== PAGE \d+ ===\n",raw)[1:] or [raw]
    found=[]; seen=set()
    with connect() as conn:
        conn.execute("DELETE FROM gbm_requirements WHERE document_id=?",(document_id,))
        for page_no,page in enumerate(pages,1):
            section=""; lines=[re.sub(r"\s+"," ",x).strip() for x in page.splitlines()]
            for line in lines:
                if not line: continue
                if len(line)<=140 and (line.isupper() or re.match(r"^\d+(?:\.\d+)*\s+",line)): section=line[:200]
                candidate=(MANDATORY_WORDS.search(line) or ATTACHMENT_WORDS.search(line) or MATCH_WORDS.search(line) or DEADLINE_WORDS.search(line) or LIMIT_WORDS.search(line))
                if not candidate or len(line)<12 or len(line)>700: continue
                normalized=line.casefold()
                if normalized in seen: continue
                seen.add(normalized); rtype="MANDATORY" if MANDATORY_WORDS.search(line) else ("CONDITIONAL" if CONDITIONAL_WORDS.search(line) else "OPTIONAL")
                confidence=0.96 if MANDATORY_WORDS.search(line) else 0.82; rid=f"req_{uuid.uuid4().hex}"; category=_classify(line)
                conn.execute("INSERT INTO gbm_requirements(requirement_id,opportunity_id,document_id,requirement_type,category,requirement_text,page_number,section,confidence,authority_rank,status,evidence_json,extracted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (rid,str(doc['opportunity_id']),document_id,rtype,category,line,page_no,section,confidence,int(doc['authority_rank']),"UNRESOLVED",json.dumps({"source_uri":doc['source_uri']}),utc_now()))
                found.append({"requirement_id":rid,"type":rtype,"category":category,"text":line,"page":page_no,"section":section,"confidence":confidence,"authority_rank":int(doc['authority_rank'])})
    return found


def effective_requirements(opportunity_id:str)->list[dict[str,Any]]:
    migrate()
    with connect() as conn: rows=conn.execute("SELECT * FROM gbm_requirements WHERE opportunity_id=? ORDER BY authority_rank, page_number, extracted_at",(opportunity_id,)).fetchall()
    out=[]; seen=set()
    for r in rows:
        key=(str(r['category']),re.sub(r"\W+"," ",str(r['requirement_text']).lower()).strip()[:120])
        if key in seen: continue
        seen.add(key); out.append(dict(r))
    return out


def _tokens(s:str)->list[str]: return re.findall(r"[a-z0-9][a-z0-9_-]{1,}",s.lower())

def _bm25(query:str,docs:list[str])->list[float]:
    q=_tokens(query); N=len(docs)
    if not N: return []
    token_docs=[_tokens(d) for d in docs]; avg=sum(map(len,token_docs))/N or 1; df=Counter()
    for toks in token_docs:
        for t in set(toks): df[t]+=1
    out=[]
    for toks in token_docs:
        tf=Counter(toks); score=0.0
        for t in q:
            idf=math.log(1+(N-df[t]+0.5)/(df[t]+0.5)); f=tf[t]; denom=f+1.5*(1-0.75+0.75*len(toks)/avg); score+=idf*(f*2.5/denom if denom else 0)
        out.append(score)
    return out


def retrieve_facts(query:str,category:str="",limit:int=14)->list[dict[str,Any]]:
    facts=list_facts(states=["VERIFIED","APPROVED","UNVERIFIED"]); docs=[f"{f['fact_key']} {f['category']} {f['value']} {f['notes']}" for f in facts]; scores=_bm25(query,docs)
    ranked=[]
    for f,s in zip(facts,scores):
        state=f['verification_state']; trust=1.0 if state in {"VERIFIED","APPROVED"} else 0.25; cat=0.8 if category and category.lower() in str(f['category']).lower() else 0.0
        total=s+cat+trust*float(f['confidence']); d=dict(f); d['retrieval_score']=round(total,5); ranked.append(d)
    ranked.sort(key=lambda x:x['retrieval_score'],reverse=True)
    return ranked[:max(1,min(limit,30))]


def split_sentences(text:str)->list[str]: return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+",text) if x.strip()]

def check_claims(text:str,evidence:list[dict[str,Any]])->list[dict[str,Any]]:
    results=[]; evidence_docs=[f"{e['fact_key']} {e['category']} {e['value']}" for e in evidence]
    for sentence in split_sentences(text):
        scores=_bm25(sentence,evidence_docs); order=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)[:3]; support=[evidence[i] for i in order if scores[i]>0.15]
        nums=set(re.findall(r"(?:\$)?\d[\d,]*(?:\.\d+)?%?",sentence)); supported_nums=set()
        for e in support: supported_nums.update(re.findall(r"(?:\$)?\d[\d,]*(?:\.\d+)?%?",str(e['value'])))
        num_ok=not nums or nums.issubset(supported_nums); projection=any(e['fact_type']=="REASONABLE_PROJECTION" for e in support)
        achieved=bool(re.search(r"\b(currently|has served|have served|achieved|operates|owns|employs|received|awarded)\b",sentence,re.I)); language_ok=not(projection and achieved)
        score=max([scores[i] for i in order],default=0.0); issues=[]
        if not support: issues.append("No supporting organizational fact retrieved")
        if not num_ok: issues.append(f"Unsupported numeric value(s): {sorted(nums-supported_nums)}")
        if not language_ok: issues.append("Projection appears to be stated as an achieved/current fact")
        results.append({"sentence":sentence,"support_fact_ids":[e['fact_id'] for e in support],"support_score":round(score,4),"numeric_supported":num_ok,"language_valid":language_ok,"issues":issues})
    return results


def score_vector(values:dict[str,Any])->dict[str,Any]:
    fields={"discovery_relevance":10,"eligibility_confidence":20,"mission_fit":12,"program_fit":12,"organizational_readiness":12,"competitive_strength":15,"deadline_feasibility":7,"financial_fit":7,"strategic_value":5}
    burden=float(values.get('administrative_burden',50)); total=0.0; explained=[]
    for k,w in fields.items():
        v=max(0,min(100,float(values.get(k,0)))); total+=v*w/100; explained.append({"factor":k,"score":v,"weight":w})
    total-=max(0,min(100,burden))*0.05
    total=max(0,min(100,total)); priority="HIGH PRIORITY" if total>=80 else "MEDIUM PRIORITY" if total>=65 else "REVIEW" if total>=45 else "REJECT"
    if float(values.get('eligibility_confidence',0))<50: priority="NEEDS INFORMATION" if float(values.get('eligibility_confidence',0))>0 else "REJECT"
    return {"final_score":round(total,1),"status":priority,"factors":explained,"administrative_burden":burden}


def calculate_budget(payload:dict[str,Any])->dict[str,Any]:
    items=payload.get('items') or []; rows=[]; direct=0.0; fringe=0.0; indirect_base=0.0
    for i,item in enumerate(items,1):
        category=str(item.get('category') or 'OTHER').upper(); qty=float(item.get('quantity',1) or 1); unit=float(item.get('unit_cost',0) or 0); months=float(item.get('months',1) or 1)
        if category=='PERSONNEL':
            salary=float(item.get('annual_salary',0) or 0); fte=float(item.get('fte',1) or 1); amount=salary*fte*(months/12); fr=amount*float(item.get('fringe_rate',0) or 0); fringe+=fr
        else: amount=qty*unit*months; fr=0.0
        direct+=amount; eligible=bool(item.get('indirect_eligible',True)); indirect_base+=amount if eligible else 0
        rows.append({"line":i,"category":category,"description":str(item.get('description') or ''),"amount":round(amount,2),"fringe":round(fr,2)})
    direct_with_fringe=direct+fringe; rate=float(payload.get('indirect_rate',0) or 0); indirect=(indirect_base+fringe)*rate
    cash=float(payload.get('cash_match',0) or 0); inkind=float(payload.get('in_kind_match',0) or 0); grant=direct_with_fringe+indirect; total=grant+cash+inkind
    participants=float(payload.get('participants',0) or 0); units=float(payload.get('housing_units',0) or 0)
    return {"items":rows,"direct_costs":round(direct,2),"fringe":round(fringe,2),"indirect_base":round(indirect_base+fringe,2),"indirect":round(indirect,2),"grant_request":round(grant,2),"cash_match":round(cash,2),"in_kind_match":round(inkind,2),"total_project_cost":round(total,2),"cost_per_participant":round(total/participants,2) if participants else None,"cost_per_housing_unit":round(total/units,2) if units else None}


def validate_logic_model(payload:dict[str,Any])->dict[str,Any]:
    required=['need','inputs','activities','outputs','short_term_outcomes','intermediate_outcomes','long_term_impact','metrics']; missing=[k for k in required if not payload.get(k)]
    metrics=payload.get('metrics') or []; metric_issues=[]
    for idx,m in enumerate(metrics):
        if not isinstance(m,dict) or not m.get('name') or not m.get('target') or not m.get('timeframe'): metric_issues.append(f"Metric {idx+1} must include name, target, and timeframe")
    return {"valid":not missing and not metric_issues,"missing":missing,"metric_issues":metric_issues}


def consistency(application_id:str)->dict[str,Any]:
    with connect() as conn: rows=conn.execute("SELECT task_key,text FROM gbm_draft_revisions WHERE application_id=? ORDER BY task_key,revision_number DESC",(application_id,)).fetchall()
    latest={}
    for r in rows: latest.setdefault(str(r['task_key']),str(r['text']))
    anchors={"money":re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?"),"percent":re.compile(r"\b\d+(?:\.\d+)?%"),"duration":re.compile(r"\b\d+\s+(?:day|days|month|months|year|years)\b",re.I),"population":re.compile(r"\b\d+\s+(?:participants?|residents?|people|individuals?|homes?|units?)\b",re.I)}
    findings=[]
    for name,rx in anchors.items():
        values={m.group(0) for text in latest.values() for m in rx.finditer(text)}
        findings.append({"category":name,"passed":len(values)<=1 or name in {'money','percent'},"values":sorted(values),"message":f"{name}: {len(values)} distinct values observed"})
    return {"application_id":application_id,"findings":findings,"passed":all(f['passed'] for f in findings)}
GBM_GRANTBOT_MASTER_INTELLIGENCE_PY

mkdir -p "$(dirname 'grantbot/master/learning.py')"
cat > 'grantbot/master/learning.py' <<'GBM_GRANTBOT_MASTER_LEARNING_PY'
from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from typing import Any

from .db import audit, connect, migrate, utc_now


def record_feedback(*,application_id:str,task_key:str,section_type:str,funder_archetype:str,before_text:str,after_text:str,accepted:bool,edit_tags:list[str],reviewer:str,reviewer_score:float|None=None,outcome:str="",award_amount:float|None=None)->dict[str,Any]:
    migrate(); fid=f"fb_{uuid.uuid4().hex}"
    with connect() as conn:
        conn.execute("INSERT INTO gbm_feedback(feedback_id,application_id,task_key,section_type,funder_archetype,before_text,after_text,accepted,edit_tags_json,reviewer,reviewer_score,outcome,award_amount,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (fid,application_id,task_key,section_type,funder_archetype,before_text,after_text,1 if accepted else 0,json.dumps(edit_tags),reviewer,reviewer_score,outcome,award_amount,utc_now()))
    audit("WRITING_FEEDBACK",reviewer,"application",application_id,{"feedback_id":fid,"tags":edit_tags,"accepted":accepted})
    return {"feedback_id":fid,"stored":True}


def _stats(text:str)->dict[str,float]:
    sentences=[s for s in re.split(r"(?<=[.!?])\s+",text.strip()) if s]; words=text.split(); paras=[p for p in text.split('\n\n') if p.strip()]
    return {"words":len(words),"avg_sentence_words":round(len(words)/len(sentences),2) if sentences else 0,"paragraphs":len(paras)}


def preference_profile(section_type:str="",funder_archetype:str="")->dict[str,Any]:
    migrate(); sql="SELECT * FROM gbm_feedback WHERE accepted=1"; args=[]
    if section_type: sql+=" AND section_type=?"; args.append(section_type)
    if funder_archetype: sql+=" AND funder_archetype=?"; args.append(funder_archetype)
    with connect() as conn: rows=conn.execute(sql,args).fetchall()
    tags=Counter(); stats=[]
    for r in rows: tags.update(json.loads(str(r['edit_tags_json']))); stats.append(_stats(str(r['after_text'])))
    if not rows: return {"samples":0,"top_edit_preferences":[],"avg_sentence_words":None,"avg_length_words":None}
    return {"samples":len(rows),"top_edit_preferences":[{"tag":k,"count":v} for k,v in tags.most_common(10)],"avg_sentence_words":round(sum(s['avg_sentence_words'] for s in stats)/len(stats),2),"avg_length_words":round(sum(s['words'] for s in stats)/len(stats),2)}


def examples(section_type:str,funder_archetype:str,query:str,limit:int=3)->list[dict[str,Any]]:
    migrate(); tokens=set(re.findall(r"[a-z0-9]+",query.lower()))
    with connect() as conn: rows=conn.execute("SELECT * FROM gbm_feedback WHERE accepted=1 ORDER BY created_at DESC LIMIT 200").fetchall()
    scored=[]
    for r in rows:
        text=str(r['after_text']); tt=set(re.findall(r"[a-z0-9]+",text.lower())); overlap=len(tokens&tt)/max(1,len(tokens|tt)); score=overlap
        if str(r['section_type'])==section_type: score+=0.5
        if str(r['funder_archetype'])==funder_archetype: score+=0.35
        if str(r['outcome']).upper()=='AWARDED': score+=0.5
        if r['reviewer_score'] is not None: score+=min(0.4,float(r['reviewer_score'])/250)
        scored.append((score,{"text":text,"section_type":r['section_type'],"funder_archetype":r['funder_archetype'],"outcome":r['outcome'],"reviewer_score":r['reviewer_score']}))
    scored.sort(key=lambda x:x[0],reverse=True); return [d for s,d in scored[:limit] if s>0.05]
GBM_GRANTBOT_MASTER_LEARNING_PY

mkdir -p "$(dirname 'grantbot/master/writer.py')"
cat > 'grantbot/master/writer.py' <<'GBM_GRANTBOT_MASTER_WRITER_PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from typing import Any

from .db import audit, connect, migrate, utc_now
from .intelligence import check_claims, retrieve_facts
from .learning import examples, preference_profile


class OllamaClient:
    def __init__(self,model:str|None=None,url:str|None=None):
        self.model=model or os.getenv('GRANTBOT_OLLAMA_MODEL','llama3.2:3b'); self.url=(url or os.getenv('OLLAMA_BASE_URL','http://127.0.0.1:11434')).rstrip('/')
    def generate(self,prompt:str,system:str)->str:
        body=json.dumps({"model":self.model,"prompt":prompt,"system":system,"stream":False,"options":{"temperature":0.25,"top_p":0.9}}).encode()
        req=urllib.request.Request(self.url+'/api/generate',data=body,headers={'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=180) as resp: data=json.loads(resp.read(20*1024*1024).decode())
        except (urllib.error.URLError,urllib.error.HTTPError,TimeoutError) as exc: raise RuntimeError(f"Ollama generation failed: {exc}") from exc
        text=str(data.get('response') or '').strip()
        if not text: raise RuntimeError('Ollama returned an empty response')
        return text
    def health(self)->dict[str,Any]:
        try:
            with urllib.request.urlopen(self.url+'/api/tags',timeout=5) as resp: data=json.loads(resp.read().decode()); names=[str(m.get('name')) for m in data.get('models',[])]
            return {"available":True,"model":self.model,"model_installed":self.model in names or any(n.startswith(self.model.split(':')[0]+':') for n in names)}
        except Exception as exc: return {"available":False,"model":self.model,"model_installed":False,"error":str(exc)}


def _limits(question:str,word_limit:int|None,character_limit:int|None)->tuple[int|None,int|None]:
    if word_limit is None:
        m=re.search(r"(?:limit|maximum|max(?:imum)?)[^\d]{0,15}(\d[\d,]*)\s*words?",question,re.I); word_limit=int(m.group(1).replace(',','')) if m else None
    if character_limit is None:
        m=re.search(r"(?:limit|maximum|max(?:imum)?)[^\d]{0,15}(\d[\d,]*)\s*characters?",question,re.I); character_limit=int(m.group(1).replace(',','')) if m else None
    return word_limit,character_limit


def _category(q:str)->str:
    low=q.lower()
    for cat,terms in {'BUDGET_FINANCE':['budget','cost','financial'],'OUTCOMES_EVALUATION':['outcome','evaluation','measure'],'ORGANIZATIONAL_CAPACITY':['capacity','experience','organization'],'NEEDS_STATEMENT':['need','problem','community'],'SUSTAINABILITY':['sustain'],'PROGRAM_NARRATIVE':['program','activity','implementation','service']}.items():
        if any(t in low for t in terms): return cat
    return 'PROGRAM_NARRATIVE'


def _save_revision(*,application_id:str,task_key:str,section_type:str,funder_archetype:str,question:str,text:str,model:str,evidence:list[dict[str,Any]],quality:dict[str,Any],status:str,actor:str,prompt:str)->dict[str,Any]:
    migrate()
    with connect() as conn:
        row=conn.execute("SELECT COALESCE(MAX(revision_number),0)+1 n FROM gbm_draft_revisions WHERE application_id=? AND task_key=?",(application_id,task_key)).fetchone(); num=int(row['n']); rid=f"rev_{uuid.uuid4().hex}"
        conn.execute("INSERT INTO gbm_draft_revisions(revision_id,application_id,task_key,revision_number,section_type,funder_archetype,question,text,model,prompt_hash,evidence_json,quality_json,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (rid,application_id,task_key,num,section_type,funder_archetype,question,text,model,hashlib.sha256(prompt.encode()).hexdigest(),json.dumps([{"fact_id":e['fact_id'],"fact_key":e['fact_key'],"state":e['verification_state']} for e in evidence]),json.dumps(quality),status,actor,utc_now()))
        for c in quality.get('claims',[]):
            conn.execute("INSERT INTO gbm_claim_checks(claim_id,revision_id,sentence,support_fact_ids_json,support_score,numeric_supported,language_valid,issues_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
              (f"claim_{uuid.uuid4().hex}",rid,c['sentence'],json.dumps(c['support_fact_ids']),float(c['support_score']),1 if c['numeric_supported'] else 0,1 if c['language_valid'] else 0,json.dumps(c['issues']),utc_now()))
    audit("DRAFT_REVISION_CREATED",actor,"application",application_id,{"revision_id":rid,"task_key":task_key,"revision_number":num,"status":status})
    return {"revision_id":rid,"revision_number":num}


def draft(*,application_id:str,opportunity_id:str,question:str,task_key:str,section_type:str|None=None,funder_archetype:str="government",word_limit:int|None=None,character_limit:int|None=None,actor:str="system",max_attempts:int=3)->dict[str,Any]:
    migrate(); section_type=section_type or _category(question); wl,cl=_limits(question,word_limit,character_limit); facts=retrieve_facts(question,section_type,limit=16); trusted=[f for f in facts if f['verification_state'] in {'VERIFIED','APPROVED'}]; planning=[f for f in facts if f['fact_type']=='REASONABLE_PROJECTION']; ex=examples(section_type,funder_archetype,question,3); prefs=preference_profile(section_type,funder_archetype); client=OllamaClient()
    if not trusted and not planning: raise ValueError("No usable organizational evidence was found for this question")
    evidence_lines='\n'.join(f"[{f['fact_id']}] {f['fact_key']} ({f['fact_type']}/{f['verification_state']}): {f['value']}" for f in trusted+planning)
    example_lines='\n\n'.join(f"APPROVED EXAMPLE:\n{x['text']}" for x in ex) or 'No approved prior example is available.'
    system=("You are GrantBot Pro's grant-writing engine. Answer the exact funder question using only supplied evidence. "
            "Never invent facts, outcomes, partners, awards, financials, property ownership, registrations, or statistics. "
            "Projection facts must be described as planned/projected, never achieved. Write specific, concise, reviewer-oriented prose. "
            "Do not mention the evidence IDs in the narrative.")
    base=f"QUESTION:\n{question}\n\nSECTION TYPE: {section_type}\nFUNDER ARCHETYPE: {funder_archetype}\nWORD LIMIT: {wl or 'none'}\nCHARACTER LIMIT: {cl or 'none'}\n\nEVIDENCE:\n{evidence_lines}\n\nLEARNED STYLE PROFILE:\n{json.dumps(prefs)}\n\n{example_lines}"
    prior=''; best=None
    for attempt in range(1,max(1,min(max_attempts,4))+1):
        prompt=base+(f"\n\nPREVIOUS DRAFT AND ISSUES:\n{prior}" if prior else '')+"\n\nWrite only the revised grant response."
        text=client.generate(prompt,system); claims=check_claims(text,trusted+planning); wc=len(text.split()); cc=len(text); issues=[]
        if wl and wc>wl: issues.append(f"Word limit exceeded: {wc}/{wl}")
        if cl and cc>cl: issues.append(f"Character limit exceeded: {cc}/{cl}")
        for c in claims: issues.extend(c['issues'])
        support_ratio=sum(1 for c in claims if not c['issues'])/max(1,len(claims)); score=round(max(0,min(100,60+40*support_ratio-8*len(set(issues)))),1); quality={"score":score,"passed":not issues and score>=85,"word_count":wc,"character_count":cc,"issues":sorted(set(issues)),"claims":claims,"attempt":attempt}
        status='READY_FOR_REVIEW' if quality['passed'] else 'DRAFT_REQUIRES_REVIEW'; saved=_save_revision(application_id=application_id,task_key=task_key,section_type=section_type,funder_archetype=funder_archetype,question=question,text=text,model=client.model,evidence=trusted+planning,quality=quality,status=status,actor=actor,prompt=prompt)
        candidate={"text":text,"quality":quality,"evidence":trusted+planning,"status":status,**saved}
        if best is None or quality['score']>best['quality']['score']: best=candidate
        if quality['passed']: break
        prior=text+"\nISSUES:\n"+'\n'.join(quality['issues'])
    assert best is not None
    return {"application_id":application_id,"opportunity_id":opportunity_id,"task_key":task_key,"section_type":section_type,"funder_archetype":funder_archetype,"model":client.model,"limits":{"word_limit":wl,"character_limit":cl},**best}
GBM_GRANTBOT_MASTER_WRITER_PY

mkdir -p "$(dirname 'grantbot/master/sources.py')"
cat > 'grantbot/master/sources.py' <<'GBM_GRANTBOT_MASTER_SOURCES_PY'
from __future__ import annotations

import csv
import json
import urllib.request
from pathlib import Path
from typing import Any

from .db import connect, migrate, utc_now
from .intelligence import score_vector


def _store(item:dict[str,Any],source:str)->dict[str,Any]:
    oid=str(item.get('opportunity_id') or item.get('id') or item.get('opportunity_number') or '').strip()
    if not oid: raise ValueError('Opportunity lacks an identifier')
    title=str(item.get('title') or item.get('name') or 'Untitled'); funder=str(item.get('agency') or item.get('funder') or item.get('agency_name') or source); deadline=str(item.get('close_date') or item.get('deadline') or '')
    scores=item.get('score_vector') or score_vector({"discovery_relevance":item.get('fit_score',50),"eligibility_confidence":item.get('eligibility_confidence',50),"mission_fit":item.get('mission_fit',50),"program_fit":item.get('program_fit',50),"organizational_readiness":item.get('readiness_score',50),"competitive_strength":item.get('final_score',50),"deadline_feasibility":70,"financial_fit":60,"strategic_value":70,"administrative_burden":40})
    with connect() as conn: conn.execute("INSERT OR REPLACE INTO gbm_opportunities(opportunity_id,source,title,funder,deadline,status,score_json,raw_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(oid,source,title,funder,deadline,str(scores['status']),json.dumps(scores),json.dumps(item,ensure_ascii=False,default=str),utc_now()))
    return {"opportunity_id":oid,"title":title,"funder":funder,"deadline":deadline,"score":scores,"source":source}


def discover_grantsgov(keywords:list[str],rows_per_keyword:int=10,deep_limit:int=0)->dict[str,Any]:
    migrate()
    try: from grantbot.pipeline.live_queue_v16 import discover_ranked_queue
    except ImportError as exc: raise RuntimeError('V16 Grants.gov live discovery module is not installed') from exc
    run=discover_ranked_queue(keywords=keywords,rows_per_keyword=rows_per_keyword,deep_limit=deep_limit); stored=[_store(i.to_dict(),'grants.gov') for i in run.items]
    return {"run":run.to_dict(),"master_opportunities":stored}


def import_csv(path:str,field_map:dict[str,str]|None=None,source:str='csv')->list[dict[str,Any]]:
    mapping=field_map or {}; p=Path(path).expanduser().resolve()
    with p.open(newline='',encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
    out=[]
    for row in rows:
        normalized={target:row.get(src,'') for target,src in mapping.items()} if mapping else dict(row)
        out.append(_store(normalized,source))
    return out


def import_json_feed(url:str,field_map:dict[str,str],source:str='json_feed')->list[dict[str,Any]]:
    req=urllib.request.Request(url,headers={'User-Agent':'GrantBotPro-Master/1.0','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as resp: data=json.loads(resp.read(20*1024*1024).decode())
    rows=data if isinstance(data,list) else data.get('items') or data.get('results') or []
    if not isinstance(rows,list): raise ValueError('JSON feed must be a list or contain items/results list')
    out=[]
    for row in rows:
        if not isinstance(row,dict): continue
        normalized={target:row.get(src,'') for target,src in field_map.items()}; out.append(_store(normalized,source))
    return out


def list_opportunities(limit:int=100)->list[dict[str,Any]]:
    with connect() as conn: rows=conn.execute("SELECT * FROM gbm_opportunities ORDER BY updated_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['score']=json.loads(str(d.pop('score_json'))); d['raw']=json.loads(str(d.pop('raw_json'))); out.append(d)
    return out
GBM_GRANTBOT_MASTER_SOURCES_PY

mkdir -p "$(dirname 'grantbot/master/operations.py')"
cat > 'grantbot/master/operations.py' <<'GBM_GRANTBOT_MASTER_OPERATIONS_PY'
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import audit, connect, migrate, utc_now


def add_deadline(opportunity_id:str,due_at:str,label:str,application_id:str="")->dict[str,Any]:
    migrate(); datetime.fromisoformat(due_at.replace('Z','+00:00')); did=f"ddl_{uuid.uuid4().hex}"; now=utc_now()
    with connect() as conn: conn.execute("INSERT INTO gbm_deadlines VALUES(?,?,?,?,?,?,?,?)",(did,opportunity_id,application_id,due_at,label,'OPEN',now,now))
    return {"deadline_id":did,"due_at":due_at,"label":label}


def due_within(days:int=30)->list[dict[str,Any]]:
    cutoff=(datetime.now(timezone.utc)+timedelta(days=days)).isoformat()
    with connect() as conn: rows=conn.execute("SELECT * FROM gbm_deadlines WHERE status='OPEN' AND due_at<=? ORDER BY due_at",(cutoff,)).fetchall()
    return [dict(r) for r in rows]


def enqueue(job_type:str,payload:dict[str,Any],run_after:str|None=None,max_attempts:int=3)->dict[str,Any]:
    migrate(); jid=f"job_{uuid.uuid4().hex}"; now=utc_now(); ra=run_after or now
    with connect() as conn: conn.execute("INSERT INTO gbm_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)",(jid,job_type,json.dumps(payload),"PENDING",0,max(1,max_attempts),ra,'','',now,now))
    return {"job_id":jid,"status":"PENDING","run_after":ra}


def portfolio()->dict[str,Any]:
    migrate()
    with connect() as conn:
        opp=dict(conn.execute("SELECT status,COUNT(*) c FROM gbm_opportunities GROUP BY status").fetchall()) if False else None
        opp_rows=conn.execute("SELECT status,COUNT(*) c FROM gbm_opportunities GROUP BY status").fetchall(); app_rows=conn.execute("SELECT stage,COUNT(*) c FROM gbm_applications GROUP BY stage").fetchall(); due=conn.execute("SELECT COUNT(*) FROM gbm_deadlines WHERE status='OPEN'").fetchone()[0]; jobs=conn.execute("SELECT status,COUNT(*) c FROM gbm_jobs GROUP BY status").fetchall()
    return {"opportunities":{r['status']:r['c'] for r in opp_rows},"applications":{r['stage']:r['c'] for r in app_rows},"open_deadlines":due,"jobs":{r['status']:r['c'] for r in jobs}}
GBM_GRANTBOT_MASTER_OPERATIONS_PY

mkdir -p "$(dirname 'grantbot/master/service.py')"
cat > 'grantbot/master/service.py' <<'GBM_GRANTBOT_MASTER_SERVICE_PY'
from __future__ import annotations

import json
import uuid
from typing import Any

from . import intelligence, knowledge, learning, operations, sources
from .db import audit, connect, health as db_health, migrate, utc_now
from .security import ensure_bootstrap_admin
from .writer import OllamaClient, draft

class MasterService:
    def initialize(self)->dict[str,Any]: return {"migration":migrate(),"admin":ensure_bootstrap_admin()}
    def health(self)->dict[str,Any]:
        return {"healthy":True,"version":"1.0.0-master","database":db_health(),"ollama":OllamaClient().health(),"submission_enabled":False,"human_approval_required":True,"portfolio":operations.portfolio()}
    def create_application(self,opportunity_id:str,title:str="",actor:str="system")->dict[str,Any]:
        migrate(); aid=f"app_{uuid.uuid4().hex}"; now=utc_now()
        with connect() as conn:
            existing=conn.execute("SELECT * FROM gbm_applications WHERE opportunity_id=?",(opportunity_id,)).fetchone()
            if existing: return dict(existing)
            conn.execute("INSERT INTO gbm_applications(application_id,opportunity_id,title,stage,requested_amount,match_amount,human_approved,approved_by,approved_at,created_at,updated_at) VALUES(?,?,?,'DRAFTING',NULL,NULL,0,'','',?,?)",(aid,opportunity_id,title,now,now))
        audit("APPLICATION_CREATED",actor,"application",aid,{"opportunity_id":opportunity_id}); return self.application(aid)
    def application(self,application_id:str)->dict[str,Any]:
        with connect() as conn:
            row=conn.execute("SELECT * FROM gbm_applications WHERE application_id=?",(application_id,)).fetchone()
            if row is None: raise FileNotFoundError(application_id)
            revs=conn.execute("SELECT * FROM gbm_draft_revisions WHERE application_id=? ORDER BY task_key,revision_number",(application_id,)).fetchall()
        d=dict(row); d['revisions']=[dict(r) for r in revs]; return d
    def approve(self,application_id:str,actor:str)->dict[str,Any]:
        now=utc_now()
        with connect() as conn:
            if conn.execute("SELECT 1 FROM gbm_applications WHERE application_id=?",(application_id,)).fetchone() is None: raise FileNotFoundError(application_id)
            conn.execute("UPDATE gbm_applications SET human_approved=1,approved_by=?,approved_at=?,stage='APPROVED',updated_at=? WHERE application_id=?",(actor,now,now,application_id))
        audit("APPLICATION_APPROVED",actor,"application",application_id,{}); return self.application(application_id)
    def gate(self,application_id:str)->dict[str,Any]:
        app=self.application(application_id); conflicts=knowledge.conflicts(); consistent=intelligence.consistency(application_id)
        with connect() as conn:
            latest=conn.execute("SELECT r.* FROM gbm_draft_revisions r JOIN (SELECT task_key,MAX(revision_number) m FROM gbm_draft_revisions WHERE application_id=? GROUP BY task_key)x ON r.task_key=x.task_key AND r.revision_number=x.m WHERE r.application_id=?",(application_id,application_id)).fetchall()
            bad_claims=0
            for r in latest: bad_claims+=conn.execute("SELECT COUNT(*) FROM gbm_claim_checks WHERE revision_id=? AND (numeric_supported=0 OR language_valid=0 OR issues_json<>'[]')",(r['revision_id'],)).fetchone()[0]
        checks=[
          {"code":"HUMAN_APPROVAL","passed":bool(app['human_approved']),"message":"Authorized human approval recorded" if app['human_approved'] else "Human approval is required"},
          {"code":"DRAFTS_PRESENT","passed":bool(latest),"message":f"{len(latest)} current draft sections"},
          {"code":"CLAIMS_SUPPORTED","passed":bad_claims==0,"message":f"{bad_claims} unsupported claim checks"},
          {"code":"KNOWLEDGE_CONFLICTS","passed":not conflicts,"message":f"{len(conflicts)} active knowledge conflicts"},
          {"code":"APPLICATION_CONSISTENCY","passed":bool(consistent['passed']),"message":"Cross-section consistency passed" if consistent['passed'] else "Cross-section consistency requires review"},
        ]; ready=all(c['passed'] for c in checks)
        return {"application_id":application_id,"ready_for_submission":ready,"submission_enabled":False,"checks":checks}

service=MasterService()
GBM_GRANTBOT_MASTER_SERVICE_PY

mkdir -p "$(dirname 'grantbot/api/master.py')"
cat > 'grantbot/api/master.py' <<'GBM_GRANTBOT_API_MASTER_PY'
from __future__ import annotations

import json
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from grantbot.master import intelligence, knowledge, learning, operations, sources
from grantbot.master.db import audit, connect, root, utc_now
from grantbot.master.security import UserContext, current_user, require
from grantbot.master.service import service
from grantbot.master.writer import draft

router=APIRouter(prefix="/master",tags=["GrantBot Master 1.0"])

class FactIn(BaseModel):
    fact_key:str; category:str="general"; value:Any; fact_type:str="USER_PROVIDED_FACT"; verification_state:str="UNVERIFIED"; source_type:str="USER"; source_ref:str=""; confidence:float=Field(default=1.0,ge=0,le=1); notes:str=""
class TextDocumentIn(BaseModel):
    text:str=Field(min_length=1); opportunity_id:str; source_uri:str; document_type:str="NOFO"; authority:str="PRIMARY_NOFO"
class WriteIn(BaseModel):
    opportunity_id:str; question:str; task_key:str; section_type:str|None=None; funder_archetype:str="government"; word_limit:int|None=Field(default=None,gt=0); character_limit:int|None=Field(default=None,gt=0); max_attempts:int=Field(default=3,ge=1,le=4)
class FeedbackIn(BaseModel):
    task_key:str; section_type:str; funder_archetype:str; before_text:str; after_text:str; accepted:bool=True; edit_tags:list[str]=Field(default_factory=list); reviewer_score:float|None=None; outcome:str=""; award_amount:float|None=None
class AppIn(BaseModel): opportunity_id:str; title:str=""
class ScoreIn(BaseModel): values:dict[str,Any]
class BudgetIn(BaseModel): payload:dict[str,Any]
class LogicIn(BaseModel): payload:dict[str,Any]
class DiscoverIn(BaseModel): keywords:list[str]=Field(min_length=1,max_length=25); rows_per_keyword:int=Field(default=10,ge=1,le=50); deep_limit:int=Field(default=0,ge=0,le=25)

@router.get('/health')
def health()->dict[str,Any]: return service.health()
@router.post('/initialize')
def initialize(user:UserContext=Depends(current_user))->dict[str,Any]: require(user,["ADMIN"]); return service.initialize()
@router.get('/facts')
def facts(user:UserContext=Depends(current_user))->list[dict[str,Any]]: return knowledge.list_facts()
@router.post('/facts')
def set_fact(payload:FactIn,user:UserContext=Depends(current_user))->dict[str,Any]: require(user,["ADMIN","REVIEWER"]); return knowledge.set_fact(**payload.model_dump(),actor=user.user_id)
@router.get('/facts/conflicts')
def conflicts(user:UserContext=Depends(current_user))->list[dict[str,Any]]: return knowledge.conflicts()
@router.post('/documents/text')
def document_text(payload:TextDocumentIn,user:UserContext=Depends(current_user))->dict[str,Any]: require(user,["ADMIN","GRANT_WRITER","REVIEWER"]); return intelligence.ingest_text(**payload.model_dump(),actor=user.user_id)
@router.post('/documents/upload')
def document_upload(opportunity_id:str=Form(default=""),authority:str=Form(default="PRIMARY_NOFO"),document_type:str=Form(default="NOFO"),file:UploadFile=File(),user:UserContext=Depends(current_user))->dict[str,Any]:
    require(user,["ADMIN","GRANT_WRITER","REVIEWER"]); name=Path(file.filename or 'upload').name; suffix=Path(name).suffix.lower()
    if suffix not in {'.pdf','.txt','.md','.csv','.json','.xml','.html','.htm'}: raise HTTPException(415,'Unsupported document type')
    target=root()/"data"/"master_upload_inbox"/f"{uuid.uuid4().hex}_{name}"; target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('wb') as out: shutil.copyfileobj(file.file,out)
    try: return intelligence.ingest_file(str(target),opportunity_id=opportunity_id,source_uri=f"upload:{name}",document_type=document_type,authority=authority,actor=user.user_id)
    finally: target.unlink(missing_ok=True)
@router.get('/requirements/{opportunity_id}')
def requirements(opportunity_id:str,user:UserContext=Depends(current_user))->list[dict[str,Any]]: return intelligence.effective_requirements(opportunity_id)
@router.post('/scores')
def scores(payload:ScoreIn,user:UserContext=Depends(current_user))->dict[str,Any]: return intelligence.score_vector(payload.values)
@router.post('/applications')
def create_app(payload:AppIn,user:UserContext=Depends(current_user))->dict[str,Any]: require(user,["ADMIN","GRANT_WRITER"]); return service.create_application(payload.opportunity_id,payload.title,user.user_id)
@router.get('/applications/{application_id}')
def application(application_id:str,user:UserContext=Depends(current_user))->dict[str,Any]: return service.application(application_id)
@router.post('/applications/{application_id}/write')
def write(application_id:str,payload:WriteIn,user:UserContext=Depends(current_user))->dict[str,Any]: require(user,["ADMIN","GRANT_WRITER"]); return draft(application_id=application_id,actor=user.user_id,**payload.model_dump())
@router.post('/applications/{application_id}/feedback')
def feedback(application_id:str,payload:FeedbackIn,user:UserContext=Depends(current_user))->dict[str,Any]: require(user,["ADMIN","REVIEWER"]); return learning.record_feedback(application_id=application_id,reviewer=user.user_id,**payload.model_dump())
@router.get('/learning/profile')
def profile(section_type:str="",funder_archetype:str="",user:UserContext=Depends(current_user))->dict[str,Any]: return learning.preference_profile(section_type,funder_archetype)
@router.post('/applications/{application_id}/approve')
def approve(application_id:str,user:UserContext=Depends(current_user))->dict[str,Any]: require(user,["ADMIN","AUTHORIZED_REPRESENTATIVE"]); return service.approve(application_id,user.user_id)
@router.get('/applications/{application_id}/gate')
def gate(application_id:str,user:UserContext=Depends(current_user))->dict[str,Any]: return service.gate(application_id)
@router.post('/budget/calculate')
def budget(payload:BudgetIn,user:UserContext=Depends(current_user))->dict[str,Any]: require(user,["ADMIN","GRANT_WRITER","FINANCIAL_REVIEWER"]); return intelligence.calculate_budget(payload.payload)
@router.post('/logic-model/validate')
def logic(payload:LogicIn,user:UserContext=Depends(current_user))->dict[str,Any]: return intelligence.validate_logic_model(payload.payload)
@router.post('/discovery/grantsgov')
def discover(payload:DiscoverIn,user:UserContext=Depends(current_user))->dict[str,Any]: require(user,["ADMIN","GRANT_WRITER"]); return sources.discover_grantsgov(payload.keywords,payload.rows_per_keyword,payload.deep_limit)
@router.get('/opportunities')
def opportunities(limit:int=100,user:UserContext=Depends(current_user))->list[dict[str,Any]]: return sources.list_opportunities(limit)
@router.get('/portfolio')
def portfolio(user:UserContext=Depends(current_user))->dict[str,Any]: return operations.portfolio()
GBM_GRANTBOT_API_MASTER_PY

mkdir -p "$(dirname 'grantbot/cli_master.py')"
cat > 'grantbot/cli_master.py' <<'GBM_GRANTBOT_CLI_MASTER_PY'
from __future__ import annotations

import argparse
import json

from grantbot.master.db import migrate
from grantbot.master.security import ensure_bootstrap_admin
from grantbot.master.service import service
from grantbot.master.sources import discover_grantsgov


def main()->int:
    p=argparse.ArgumentParser(prog='grantbot-master'); sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('health'); sub.add_parser('migrate'); sub.add_parser('key')
    d=sub.add_parser('discover'); d.add_argument('keywords',nargs='+'); d.add_argument('--rows',type=int,default=5); d.add_argument('--deep',type=int,default=0)
    g=sub.add_parser('gate'); g.add_argument('application_id')
    a=p.parse_args()
    if a.cmd=='health': out=service.health()
    elif a.cmd=='migrate': out=migrate()
    elif a.cmd=='key': out=ensure_bootstrap_admin()
    elif a.cmd=='discover': out=discover_grantsgov(a.keywords,a.rows,a.deep)
    else: out=service.gate(a.application_id)
    print(json.dumps(out,indent=2,ensure_ascii=False,default=str)); return 0

if __name__=='__main__': raise SystemExit(main())
GBM_GRANTBOT_CLI_MASTER_PY

mkdir -p "$(dirname 'tests/test_master_v1.py')"
cat > 'tests/test_master_v1.py' <<'GBM_TESTS_TEST_MASTER_V1_PY'
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grantbot.master import intelligence, knowledge, learning
from grantbot.master.db import health, migrate
from grantbot.master.security import authenticate, ensure_bootstrap_admin, key_file
from grantbot.master.service import service

class MasterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=Path(self.tmp.name)/'grantbot.db'; self.root=Path(self.tmp.name)/'root'; self.root.mkdir()
        self.env=patch.dict(os.environ,{"GRANTBOT_DB_PATH":str(self.db),"GRANTBOT_ROOT":str(self.root)}); self.env.start(); migrate()
    def tearDown(self): self.env.stop(); self.tmp.cleanup()
    def test_schema(self): self.assertTrue(health()['healthy'])
    def test_fact_versioning(self):
        knowledge.set_fact(fact_key='sobriety',category='policy',value='6 months',fact_type='USER_PROVIDED_FACT',verification_state='VERIFIED',source_type='USER')
        knowledge.set_fact(fact_key='sobriety',category='policy',value='30 days',fact_type='USER_PROVIDED_FACT',verification_state='VERIFIED',source_type='USER')
        self.assertEqual(knowledge.get_fact('sobriety')['value'],'30 days')
    def test_budget(self):
        r=intelligence.calculate_budget({'items':[{'category':'PERSONNEL','annual_salary':60000,'fte':.5,'months':12,'fringe_rate':.2},{'category':'SUPPLIES','quantity':2,'unit_cost':1000,'months':1}],'indirect_rate':.1})
        self.assertEqual(r['direct_costs'],32000.0); self.assertEqual(r['fringe'],6000.0)
    def test_logic(self):
        p={'need':'x','inputs':['a'],'activities':['b'],'outputs':['c'],'short_term_outcomes':['d'],'intermediate_outcomes':['e'],'long_term_impact':['f'],'metrics':[{'name':'served','target':10,'timeframe':'year 1'}]}
        self.assertTrue(intelligence.validate_logic_model(p)['valid'])
    def test_claim_projection_language(self):
        f=knowledge.set_fact(fact_key='homes',category='housing',value='10 planned homes',fact_type='REASONABLE_PROJECTION',verification_state='APPROVED',source_type='USER')
        checks=intelligence.check_claims('The organization currently operates 10 homes.',[f]); self.assertFalse(checks[0]['language_valid'])
    def test_learning(self):
        learning.record_feedback(application_id='a',task_key='t',section_type='NEEDS_STATEMENT',funder_archetype='government',before_text='Long beginning.',after_text='Evidence first.',accepted=True,edit_tags=['remove_intro'],reviewer='r')
        self.assertEqual(learning.preference_profile('NEEDS_STATEMENT','government')['samples'],1)
    def test_auth(self):
        ensure_bootstrap_admin(); key=key_file().read_text().strip(); self.assertIn('ADMIN',authenticate(key).roles)
    def test_gate_blocks_unapproved(self):
        app=service.create_application('opp1','Test'); gate=service.gate(app['application_id']); self.assertFalse(gate['ready_for_submission'])

if __name__=='__main__': unittest.main()
GBM_TESTS_TEST_MASTER_V1_PY

mkdir -p "$(dirname '.github/workflows/grantbot-ci.yml')"
cat > '.github/workflows/grantbot-ci.yml' <<'GBM__GITHUB_WORKFLOWS_GRANTBOT_CI_YML'
name: GrantBot CI
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install --upgrade pip
      - run: pip install -r requirements.txt
      - run: python -m compileall -q grantbot
      - run: python -m unittest discover -s tests -v
GBM__GITHUB_WORKFLOWS_GRANTBOT_CI_YML

touch grantbot/master/__init__.py grantbot/api/__init__.py
$PY - <<'PY_PATCH'
from pathlib import Path
p=Path('grantbot/app.py'); s=p.read_text(encoding='utf-8')
marker='# GRANTBOT MASTER 1.0 ROUTER'
if marker not in s:
    s=s.rstrip()+"\n\n"+marker+"\nfrom grantbot.api.master import router as grantbot_master_router\napp.include_router(grantbot_master_router)\n"
    p.write_text(s,encoding='utf-8')
print('MASTER ROUTER REGISTERED')
PY_PATCH
$PY -m py_compile grantbot/master/*.py grantbot/api/master.py grantbot/cli_master.py grantbot/app.py tests/test_master_v1.py
$PY -m unittest tests.test_master_v1 -v
$PY - <<'PY_INIT'
from grantbot.master.service import service
from grantbot.master.security import ensure_bootstrap_admin
print(service.initialize())
print(service.health())
PY_INIT
$PY -m compileall -q grantbot
if [[ "${GRANTBOT_SKIP_FULL_TESTS:-0}" != "1" ]]; then $PY -m unittest discover -s tests -v; fi
$PY - <<'PY_ROUTES'
import grantbot.app
paths=set(grantbot.app.app.openapi().get('paths',{}))
required={'/master/health','/master/facts','/master/documents/upload','/master/applications/{application_id}/write','/master/applications/{application_id}/gate','/master/discovery/grantsgov'}
missing=required-paths
if missing: raise SystemExit(f'Missing master routes: {sorted(missing)}')
print('GRANTBOT MASTER ROUTES: OK')
PY_ROUTES
cat > "$HOME/grantbot-master" <<EOF_CLI
#!/usr/bin/env bash
set -Eeuo pipefail
cd "$ROOT"
exec "$PY" -m grantbot.cli_master "\$@"
EOF_CLI
chmod +x "$HOME/grantbot-master"
if [[ "${GRANTBOT_SKIP_SERVER:-0}" != "1" ]]; then
  pkill -f '[u]vicorn.*grantbot.app:app' 2>/dev/null || true
  nohup "$PY" -m uvicorn grantbot.app:app --host 127.0.0.1 --port 8000 > logs/uvicorn.log 2>&1 &
  for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/master/health >/dev/null 2>&1 && break; sleep 1; done
  curl -fsS http://127.0.0.1:8000/master/health >/dev/null
fi
echo
echo '============================================================'
echo ' GRANTBOT MASTER 1.0 — CONSOLIDATED PLATFORM INSTALLED'
echo '============================================================'
echo "Root: $ROOT"
echo "API: http://127.0.0.1:8000/docs"
echo "Health: http://127.0.0.1:8000/master/health"
echo "CLI: $HOME/grantbot-master"
echo "API key file: $ROOT/data/master_api_key.txt"
echo 'Legacy V13–V19 routes remain available as compatibility layers.'
echo 'Autonomous final submission remains BLOCKED.'
echo '============================================================'
