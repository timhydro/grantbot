#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${HOME}/grantbot_pro"
VENV="${ROOT}/.venv"

echo
echo "============================================================"
echo " GRANTBOT PRO"
echo " MODULE 01 — MASTER CORE / FOUNDATION"
echo "============================================================"
echo

# ------------------------------------------------------------
# 1. REQUIRE PYTHON
# ------------------------------------------------------------

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: Python 3 is not installed."
    echo "Install Python 3 before continuing."
    exit 1
fi

echo "Python:"
python3 --version

# ------------------------------------------------------------
# 2. CREATE MASTER TREE
# ------------------------------------------------------------

echo
echo "=== Creating GrantBot master tree ==="

mkdir -p \
    "$ROOT/grantbot" \
    "$ROOT/grantbot/core" \
    "$ROOT/grantbot/knowledge" \
    "$ROOT/grantbot/funding" \
    "$ROOT/grantbot/grants" \
    "$ROOT/grantbot/investors" \
    "$ROOT/grantbot/discovery" \
    "$ROOT/grantbot/nofo" \
    "$ROOT/grantbot/eligibility" \
    "$ROOT/grantbot/matching" \
    "$ROOT/grantbot/writer" \
    "$ROOT/grantbot/claims" \
    "$ROOT/grantbot/budget" \
    "$ROOT/grantbot/evidence" \
    "$ROOT/grantbot/proposals" \
    "$ROOT/grantbot/compliance" \
    "$ROOT/grantbot/outcomes" \
    "$ROOT/grantbot/ai" \
    "$ROOT/grantbot/api" \
    "$ROOT/grantbot/web" \
    "$ROOT/grantbot/templates" \
    "$ROOT/grantbot/static" \
    "$ROOT/data" \
    "$ROOT/data/imports" \
    "$ROOT/data/cache" \
    "$ROOT/data/knowledge" \
    "$ROOT/data/funding" \
    "$ROOT/data/investors" \
    "$ROOT/data/nofo" \
    "$ROOT/logs" \
    "$ROOT/exports" \
    "$ROOT/backups" \
    "$ROOT/tests" \
    "$ROOT/scripts"

touch "$ROOT/grantbot/__init__.py"

for package in \
    core knowledge funding grants investors discovery nofo \
    eligibility matching writer claims budget evidence proposals \
    compliance outcomes ai api web
do
    touch "$ROOT/grantbot/${package}/__init__.py"
done

touch "$ROOT/tests/__init__.py"

# ------------------------------------------------------------
# 3. REQUIREMENTS
# ------------------------------------------------------------

cat > "$ROOT/requirements.txt" <<'REQ'
Flask>=3.0,<4
requests>=2.31,<3
python-dotenv>=1.0,<2
beautifulsoup4>=4.12,<5
lxml>=5,<7
pypdf>=5,<7
python-docx>=1.1,<2
openpyxl>=3.1,<4
pytest>=8,<10
gunicorn>=22,<24
REQ

# ------------------------------------------------------------
# 4. PROJECT METADATA
# ------------------------------------------------------------

cat > "$ROOT/pyproject.toml" <<'TOML'
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "grantbot-pro"
version = "4.0.0"
description = "Grant and funding intelligence platform for BrokenGrowthMinistries"
requires-python = ">=3.10"

[project.scripts]
grantbot = "grantbot.__main__:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
TOML

# ------------------------------------------------------------
# 5. ENVIRONMENT
# ------------------------------------------------------------

cat > "$ROOT/.env.example" <<'ENV'
GRANTBOT_ENVIRONMENT=development

GRANTBOT_HOST=127.0.0.1
GRANTBOT_PORT=5000
GRANTBOT_DEBUG=0

GRANTBOT_ORGANIZATION=BrokenGrowthMinistries
GRANTBOT_LOG_LEVEL=INFO

GRANTBOT_REQUEST_TIMEOUT=30
GRANTBOT_DATABASE=data/grantbot.db

OLLAMA_ENABLED=0
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2
ENV

if [ ! -f "$ROOT/.env" ]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
fi

# ------------------------------------------------------------
# 6. PACKAGE IDENTITY
# ------------------------------------------------------------

cat > "$ROOT/grantbot/__init__.py" <<'PY'
"""
GrantBot Pro
BrokenGrowthMinistries Funding Intelligence Platform
"""

__version__ = "4.0.0"
__app_name__ = "GrantBot Pro"
__organization__ = "BrokenGrowthMinistries"
PY

# ------------------------------------------------------------
# 7. ERROR SYSTEM
# ------------------------------------------------------------

cat > "$ROOT/grantbot/core/errors.py" <<'PY'
class GrantBotError(Exception):
    """Base exception for GrantBot Pro."""


class ConfigurationError(GrantBotError):
    """Configuration is invalid."""


class DatabaseError(GrantBotError):
    """Database operation failed."""


class ValidationError(GrantBotError):
    """Input or stored data failed validation."""


class MigrationError(GrantBotError):
    """Database migration failed."""


class ExternalServiceError(GrantBotError):
    """External API/service failed."""


class FundingSourceError(GrantBotError):
    """Funding-source operation failed."""


class EligibilityError(GrantBotError):
    """Eligibility analysis failed."""


class MatchingError(GrantBotError):
    """Funding match analysis failed."""


class UnsafeClaimError(GrantBotError):
    """An unsupported application claim was detected."""


class NofoParsingError(GrantBotError):
    """NOFO/document parsing failed."""
PY

# ------------------------------------------------------------
# 8. CONFIGURATION ENGINE
# ------------------------------------------------------------

cat > "$ROOT/grantbot/core/config.py" <<'PY'
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(
    os.environ.get(
        "GRANTBOT_ROOT",
        Path(__file__).resolve().parents[2],
    )
).expanduser().resolve()

load_dotenv(PROJECT_ROOT / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)

    if raw is None:
        return default

    return raw.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)

    if raw is None:
        return default

    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be an integer. Received {raw!r}."
        ) from exc


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT

    data_dir: Path = PROJECT_ROOT / "data"
    log_dir: Path = PROJECT_ROOT / "logs"
    export_dir: Path = PROJECT_ROOT / "exports"
    backup_dir: Path = PROJECT_ROOT / "backups"

    environment: str = os.getenv(
        "GRANTBOT_ENVIRONMENT",
        "development",
    )

    organization_name: str = os.getenv(
        "GRANTBOT_ORGANIZATION",
        "BrokenGrowthMinistries",
    )

    host: str = os.getenv(
        "GRANTBOT_HOST",
        "127.0.0.1",
    )

    port: int = env_int(
        "GRANTBOT_PORT",
        5000,
    )

    debug: bool = env_bool(
        "GRANTBOT_DEBUG",
        False,
    )

    log_level: str = os.getenv(
        "GRANTBOT_LOG_LEVEL",
        "INFO",
    ).upper()

    request_timeout: int = env_int(
        "GRANTBOT_REQUEST_TIMEOUT",
        30,
    )

    ollama_enabled: bool = env_bool(
        "OLLAMA_ENABLED",
        False,
    )

    ollama_url: str = os.getenv(
        "OLLAMA_URL",
        "http://127.0.0.1:11434",
    )

    ollama_model: str = os.getenv(
        "OLLAMA_MODEL",
        "llama3.2",
    )

    @property
    def database_path(self) -> Path:
        raw = os.getenv(
            "GRANTBOT_DATABASE",
            "data/grantbot.db",
        )

        path = Path(raw)

        if not path.is_absolute():
            path = self.project_root / path

        return path.resolve()

    def ensure_directories(self) -> None:
        directories = [
            self.data_dir,
            self.log_dir,
            self.export_dir,
            self.backup_dir,
            self.data_dir / "imports",
            self.data_dir / "cache",
            self.data_dir / "knowledge",
            self.data_dir / "funding",
            self.data_dir / "investors",
            self.data_dir / "nofo",
        ]

        for directory in directories:
            directory.mkdir(
                parents=True,
                exist_ok=True,
            )


settings = Settings()
settings.ensure_directories()
PY

# ------------------------------------------------------------
# 9. LOGGING ENGINE
# ------------------------------------------------------------

cat > "$ROOT/grantbot/core/logging_config.py" <<'PY'
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from grantbot.core.config import settings


_CONFIGURED = False


def configure_logging() -> logging.Logger:
    global _CONFIGURED

    logger = logging.getLogger("grantbot")

    if _CONFIGURED:
        return logger

    level = getattr(
        logging,
        settings.log_level,
        logging.INFO,
    )

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)

    logfile = settings.log_dir / "grantbot.log"

    rotating = RotatingFileHandler(
        logfile,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )

    rotating.setLevel(level)
    rotating.setFormatter(formatter)

    logger.addHandler(console)
    logger.addHandler(rotating)

    _CONFIGURED = True

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    root = configure_logging()

    if not name:
        return root

    return root.getChild(name)
PY

# ------------------------------------------------------------
# 10. SHARED UTILITIES
# ------------------------------------------------------------

cat > "$ROOT/grantbot/core/utils.py" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def normalize_text(value: str | None) -> str:
    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def slugify(value: str) -> str:
    value = normalize_text(value).lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value,
    )

    return value.strip("-")


def safe_json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
    )


def safe_json_loads(
    value: str | None,
    default: Any = None,
) -> Any:
    if not value:
        return default

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def sha256_file(path: str | Path) -> str:
    path = Path(path)

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()
PY

# ------------------------------------------------------------
# 11. MASTER DATABASE ENGINE
# ------------------------------------------------------------

cat > "$ROOT/grantbot/core/database.py" <<'PY'
from __future__ import annotations

import json
import shutil
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from grantbot.core.config import settings
from grantbot.core.errors import DatabaseError
from grantbot.core.logging_config import get_logger


logger = get_logger("database")

CURRENT_SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS system_meta (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        category TEXT NOT NULL,

        fact_key TEXT NOT NULL UNIQUE,

        value TEXT,

        status TEXT NOT NULL DEFAULT 'MISSING'
        CHECK (
            status IN (
                'APPROVED',
                'VERIFIED',
                'DRAFT',
                'MISSING'
            )
        ),

        source TEXT,

        confidence REAL DEFAULT 1.0,

        notes TEXT,

        created_at TEXT NOT NULL,

        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_facts_category
    ON facts(category);

    CREATE INDEX IF NOT EXISTS idx_facts_status
    ON facts(status);


    CREATE TABLE IF NOT EXISTS funding_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        source_type TEXT NOT NULL,

        source_name TEXT NOT NULL,

        jurisdiction_level TEXT,

        geography TEXT,

        website TEXT,

        api_endpoint TEXT,

        active INTEGER DEFAULT 1,

        metadata_json TEXT,

        created_at TEXT NOT NULL,

        updated_at TEXT NOT NULL,

        UNIQUE(
            source_type,
            source_name,
            geography
        )
    );


    CREATE TABLE IF NOT EXISTS opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        external_id TEXT,

        funding_source_id INTEGER,

        opportunity_type TEXT NOT NULL DEFAULT 'GRANT',

        title TEXT NOT NULL,

        funder TEXT,

        agency TEXT,

        description TEXT,

        eligibility TEXT,

        geography TEXT,

        opening_date TEXT,

        deadline TEXT,

        award_floor REAL,

        award_ceiling REAL,

        estimated_total REAL,

        opportunity_number TEXT,

        assistance_listing TEXT,

        source_url TEXT,

        status TEXT DEFAULT 'DISCOVERED',

        raw_json TEXT,

        created_at TEXT NOT NULL,

        updated_at TEXT NOT NULL,

        FOREIGN KEY(funding_source_id)
        REFERENCES funding_sources(id)
        ON DELETE SET NULL,

        UNIQUE(
            external_id,
            funding_source_id
        )
    );

    CREATE INDEX IF NOT EXISTS idx_opportunities_deadline
    ON opportunities(deadline);

    CREATE INDEX IF NOT EXISTS idx_opportunities_type
    ON opportunities(opportunity_type);

    CREATE INDEX IF NOT EXISTS idx_opportunities_status
    ON opportunities(status);


    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        opportunity_id INTEGER NOT NULL,

        overall_score REAL NOT NULL,

        priority TEXT NOT NULL,

        eligible INTEGER NOT NULL DEFAULT 1,

        eligibility_score REAL DEFAULT 0,

        mission_score REAL DEFAULT 0,

        population_score REAL DEFAULT 0,

        geography_score REAL DEFAULT 0,

        program_score REAL DEFAULT 0,

        funding_score REAL DEFAULT 0,

        readiness_score REAL DEFAULT 0,

        deadline_score REAL DEFAULT 0,

        competition_score REAL DEFAULT 0,

        relationship_score REAL DEFAULT 0,

        reasons_json TEXT,

        warnings_json TEXT,

        created_at TEXT NOT NULL,

        FOREIGN KEY(opportunity_id)
        REFERENCES opportunities(id)
        ON DELETE CASCADE
    );


    CREATE TABLE IF NOT EXISTS organizations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        name TEXT NOT NULL,

        organization_type TEXT,

        ein TEXT,

        website TEXT,

        geography TEXT,

        metadata_json TEXT,

        created_at TEXT NOT NULL,

        updated_at TEXT NOT NULL
    );


    CREATE TABLE IF NOT EXISTS investors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        name TEXT NOT NULL,

        investor_type TEXT,

        organization TEXT,

        geography TEXT,

        investment_focus TEXT,

        stage_preferences TEXT,

        check_size_min REAL,

        check_size_max REAL,

        impact_focus TEXT,

        website TEXT,

        contact_json TEXT,

        relationship_json TEXT,

        metadata_json TEXT,

        created_at TEXT NOT NULL,

        updated_at TEXT NOT NULL
    );


    CREATE TABLE IF NOT EXISTS proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        opportunity_id INTEGER,

        title TEXT NOT NULL,

        status TEXT NOT NULL DEFAULT 'DRAFT',

        requested_amount REAL,

        submission_deadline TEXT,

        created_at TEXT NOT NULL,

        updated_at TEXT NOT NULL,

        FOREIGN KEY(opportunity_id)
        REFERENCES opportunities(id)
        ON DELETE SET NULL
    );


    CREATE TABLE IF NOT EXISTS proposal_sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        proposal_id INTEGER NOT NULL,

        section_key TEXT NOT NULL,

        section_name TEXT NOT NULL,

        prompt TEXT,

        narrative TEXT,

        safe_to_submit INTEGER DEFAULT 0,

        verification_json TEXT,

        created_at TEXT NOT NULL,

        updated_at TEXT NOT NULL,

        UNIQUE(
            proposal_id,
            section_key
        ),

        FOREIGN KEY(proposal_id)
        REFERENCES proposals(id)
        ON DELETE CASCADE
    );


    CREATE TABLE IF NOT EXISTS evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        title TEXT NOT NULL,

        category TEXT,

        content TEXT NOT NULL,

        source TEXT,

        source_date TEXT,

        verified INTEGER DEFAULT 0,

        confidence REAL DEFAULT 1.0,

        created_at TEXT NOT NULL,

        updated_at TEXT NOT NULL
    );


    CREATE TABLE IF NOT EXISTS requirements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        opportunity_id INTEGER NOT NULL,

        requirement_type TEXT NOT NULL,

        requirement_text TEXT NOT NULL,

        required INTEGER DEFAULT 1,

        satisfied INTEGER DEFAULT 0,

        notes TEXT,

        created_at TEXT NOT NULL,

        updated_at TEXT NOT NULL,

        FOREIGN KEY(opportunity_id)
        REFERENCES opportunities(id)
        ON DELETE CASCADE
    );


    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        action TEXT NOT NULL,

        entity_type TEXT,

        entity_id TEXT,

        details_json TEXT,

        created_at TEXT NOT NULL
    );
    """
}


def _connect() -> sqlite3.Connection:
    try:
        settings.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        conn = sqlite3.connect(
            settings.database_path,
            timeout=30,
        )

        conn.row_factory = sqlite3.Row

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        conn.execute(
            "PRAGMA journal_mode = WAL"
        )

        conn.execute(
            "PRAGMA synchronous = NORMAL"
        )

        conn.execute(
            "PRAGMA busy_timeout = 30000"
        )

        return conn

    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Unable to open GrantBot database: {exc}"
        ) from exc


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = _connect()

    try:
        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def current_schema_version(
    conn: sqlite3.Connection,
) -> int:

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        )
        """
    )

    row = conn.execute(
        """
        SELECT version
        FROM schema_version
        LIMIT 1
        """
    ).fetchone()

    if row is None:
        conn.execute(
            """
            INSERT INTO schema_version(version)
            VALUES (0)
            """
        )

        return 0

    return int(row["version"])


def migrate() -> None:
    with connection() as conn:
        version = current_schema_version(
            conn
        )

        for target in sorted(MIGRATIONS):
            if target <= version:
                continue

            logger.info(
                "Applying database migration %s",
                target,
            )

            conn.executescript(
                MIGRATIONS[target]
            )

            conn.execute(
                """
                UPDATE schema_version
                SET version=?
                """,
                (target,),
            )

            version = target

    logger.info(
        "Database schema version %s ready.",
        version,
    )


def execute(
    sql: str,
    params: tuple | dict = (),
) -> int:

    try:
        with connection() as conn:
            cursor = conn.execute(
                sql,
                params,
            )

            return int(
                cursor.lastrowid or 0
            )

    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Database write failed: {exc}"
        ) from exc


def fetch_one(
    sql: str,
    params: tuple | dict = (),
) -> dict[str, Any] | None:

    try:
        with connection() as conn:
            row = conn.execute(
                sql,
                params,
            ).fetchone()

        return dict(row) if row else None

    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Database query failed: {exc}"
        ) from exc


def fetch_all(
    sql: str,
    params: tuple | dict = (),
) -> list[dict[str, Any]]:

    try:
        with connection() as conn:
            rows = conn.execute(
                sql,
                params,
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Database query failed: {exc}"
        ) from exc


def audit(
    action: str,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    details: dict | None = None,
) -> None:

    execute(
        """
        INSERT INTO audit_log(
            action,
            entity_type,
            entity_id,
            details_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            action,
            entity_type,
            str(entity_id)
            if entity_id is not None
            else None,
            json.dumps(
                details or {},
                ensure_ascii=False,
            ),
            utc_now(),
        ),
    )


def backup_database() -> Path | None:
    source = settings.database_path

    if not source.exists():
        return None

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    destination = (
        settings.backup_dir
        / f"grantbot_{timestamp}.db"
    )

    shutil.copy2(
        source,
        destination,
    )

    return destination


def health_check() -> dict[str, Any]:
    try:
        with connection() as conn:
            db_ok = conn.execute(
                "SELECT 1 AS ok"
            ).fetchone()

            version = current_schema_version(
                conn
            )

            tables = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                ORDER BY name
                """
            ).fetchall()

        return {
            "healthy":
                bool(
                    db_ok
                    and db_ok["ok"] == 1
                ),

            "database":
                str(
                    settings.database_path
                ),

            "schema_version":
                version,

            "tables": [
                row["name"]
                for row in tables
            ],
        }

    except Exception as exc:
        return {
            "healthy": False,
            "database":
                str(
                    settings.database_path
                ),
            "error":
                str(exc),
        }


def initialize_database() -> None:
    settings.ensure_directories()

    migrate()

    now = utc_now()

    execute(
        """
        INSERT INTO system_meta(
            key,
            value,
            updated_at
        )
        VALUES(
            'application',
            'GrantBot Pro',
            ?
        )
        ON CONFLICT(key)
        DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
        """,
        (now,),
    )

    execute(
        """
        INSERT INTO system_meta(
            key,
            value,
            updated_at
        )
        VALUES(
            'organization',
            ?,
            ?
        )
        ON CONFLICT(key)
        DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
        """,
        (
            settings.organization_name,
            now,
        ),
    )
PY

# ------------------------------------------------------------
# 12. DIAGNOSTICS ENGINE
# ------------------------------------------------------------

cat > "$ROOT/grantbot/core/diagnostics.py" <<'PY'
from __future__ import annotations

import platform
import sys

from grantbot import (
    __app_name__,
    __organization__,
    __version__,
)

from grantbot.core.config import settings
from grantbot.core.database import health_check


def system_status() -> dict:
    return {
        "application": __app_name__,
        "version": __version__,
        "organization": __organization__,
        "environment":
            settings.environment,
        "python":
            sys.version.split()[0],
        "platform":
            platform.platform(),
        "project_root":
            str(
                settings.project_root
            ),
        "host":
            settings.host,
        "port":
            settings.port,
        "ollama_enabled":
            settings.ollama_enabled,
        "database":
            health_check(),
    }
PY

# ------------------------------------------------------------
# 13. INITIAL CLI
# ------------------------------------------------------------

cat > "$ROOT/grantbot/__main__.py" <<'PY'
from __future__ import annotations

import argparse
import json

from grantbot import __version__
from grantbot.core.database import (
    backup_database,
    initialize_database,
)
from grantbot.core.diagnostics import system_status


def pretty(value):
    print(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="grantbot",
        description=(
            "GrantBot Pro — BrokenGrowthMinistries "
            "funding intelligence platform"
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"GrantBot Pro {__version__}",
    )

    commands = parser.add_subparsers(
        dest="command"
    )

    commands.add_parser(
        "status",
        help="Run complete GrantBot diagnostics.",
    )

    commands.add_parser(
        "init",
        help="Initialize database and directories.",
    )

    commands.add_parser(
        "backup",
        help="Backup the GrantBot database.",
    )

    commands.add_parser(
        "tree",
        help="Display the GrantBot project structure.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        initialize_database()
        print("GrantBot core initialized.")
        return

    if args.command == "status":
        initialize_database()
        pretty(
            system_status()
        )
        return

    if args.command == "backup":
        initialize_database()

        path = backup_database()

        if path:
            print(
                f"Backup created: {path}"
            )
        else:
            print(
                "No database exists yet."
            )

        return

    if args.command == "tree":
        from grantbot.core.config import settings

        for path in sorted(
            settings.project_root.rglob("*")
        ):
            relative = path.relative_to(
                settings.project_root
            )

            if ".venv" in relative.parts:
                continue

            print(relative)

        return

    parser.print_help()


if __name__ == "__main__":
    main()
PY

# ------------------------------------------------------------
# 14. CORE TESTS
# ------------------------------------------------------------

cat > "$ROOT/tests/test_core.py" <<'PY'
from grantbot.core.config import settings
from grantbot.core.database import (
    health_check,
    initialize_database,
)
from grantbot.core.utils import (
    normalize_text,
    safe_json_dumps,
    safe_json_loads,
    slugify,
)


def test_directories():
    settings.ensure_directories()

    assert settings.data_dir.exists()
    assert settings.log_dir.exists()
    assert settings.export_dir.exists()
    assert settings.backup_dir.exists()


def test_database():
    initialize_database()

    result = health_check()

    assert result["healthy"] is True
    assert result["schema_version"] >= 1

    assert "facts" in result["tables"]
    assert "funding_sources" in result["tables"]
    assert "opportunities" in result["tables"]
    assert "investors" in result["tables"]
    assert "proposals" in result["tables"]


def test_text_normalizer():
    result = normalize_text(
        "Broken   Growth\n Ministries"
    )

    assert result == "Broken Growth Ministries"


def test_slugify():
    assert (
        slugify(
            "Broken Growth Ministries!"
        )
        == "broken-growth-ministries"
    )


def test_json_helpers():
    source = {
        "hello": "world",
        "number": 7,
    }

    encoded = safe_json_dumps(
        source
    )

    decoded = safe_json_loads(
        encoded
    )

    assert decoded == source
PY

# ------------------------------------------------------------
# 15. MASTER BOOTSTRAP
# ------------------------------------------------------------

cat > "$ROOT/bootstrap.sh" <<'BOOTSTRAP'
#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo
echo "============================================"
echo " GRANTBOT PRO BOOTSTRAP"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: Python 3 is required."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."

    if ! python3 -m venv .venv; then
        echo
        echo "Python venv support is missing."
        echo
        echo "On Debian/Chromebook Linux run:"
        echo
        echo "sudo apt update && sudo apt install -y python3-venv"
        echo
        exit 1
    fi
fi

echo
echo "Upgrading pip..."
.venv/bin/python -m pip install \
    --upgrade \
    pip \
    setuptools \
    wheel

echo
echo "Installing GrantBot dependencies..."
.venv/bin/pip install \
    -r requirements.txt

echo
echo "Compiling source..."
.venv/bin/python \
    -m compileall \
    -q \
    grantbot \
    tests

echo
echo "Initializing database..."
PYTHONPATH="$ROOT" \
.venv/bin/python \
    -m grantbot init

echo
echo "Running tests..."
PYTHONPATH="$ROOT" \
.venv/bin/python \
    -m pytest \
    tests/test_core.py \
    -q

echo
echo "Running diagnostics..."
PYTHONPATH="$ROOT" \
.venv/bin/python \
    -m grantbot status

echo
echo "============================================"
echo " MODULE 01 FOUNDATION READY"
echo "============================================"
BOOTSTRAP

chmod +x "$ROOT/bootstrap.sh"

# ------------------------------------------------------------
# 16. MODULE INSTALLATION
# ------------------------------------------------------------

echo
echo "=== Checking Python venv support ==="

if [ ! -d "$VENV" ]; then
    if ! python3 -m venv "$VENV"; then
        echo
        echo "============================================================"
        echo " MODULE FILES WERE CREATED SUCCESSFULLY"
        echo " BUT PYTHON VENV SUPPORT IS MISSING"
        echo "============================================================"
        echo
        echo "Run:"
        echo
        echo "sudo apt update && sudo apt install -y python3-venv"
        echo
        echo "Then run:"
        echo
        echo "cd ~/grantbot_pro && bash bootstrap.sh"
        echo
        exit 0
    fi
fi

echo
echo "=== Installing shared dependencies ==="

"$VENV/bin/python" -m pip install \
    --upgrade \
    pip \
    setuptools \
    wheel

"$VENV/bin/pip" install \
    -r "$ROOT/requirements.txt"

echo
echo "=== Compiling Module 01 ==="

cd "$ROOT"

"$VENV/bin/python" \
    -m compileall \
    -q \
    grantbot \
    tests

echo
echo "=== Initializing GrantBot database ==="

PYTHONPATH="$ROOT" \
"$VENV/bin/python" \
    -m grantbot init

echo
echo "=== Running Module 01 tests ==="

PYTHONPATH="$ROOT" \
"$VENV/bin/python" \
    -m pytest \
    tests/test_core.py \
    -q

echo
echo "=== Running full core diagnostics ==="

PYTHONPATH="$ROOT" \
"$VENV/bin/python" \
    -m grantbot status

echo
echo "============================================================"
echo " MODULE 01 INSTALLED SUCCESSFULLY"
echo "============================================================"
echo
echo "Root:"
echo "  ~/grantbot_pro"
echo
echo "Virtual environment:"
echo "  ~/grantbot_pro/.venv"
echo
echo "Database:"
echo "  ~/grantbot_pro/data/grantbot.db"
echo
echo "Logs:"
echo "  ~/grantbot_pro/logs/grantbot.log"
echo
echo "Test it anytime with:"
echo
echo "  cd ~/grantbot_pro && .venv/bin/python -m grantbot status"
echo
echo "View the complete tree:"
echo
echo "  cd ~/grantbot_pro && .venv/bin/python -m grantbot tree"
echo
echo "NEXT MODULE:"
echo "  Module 02 — BrokenGrowth Knowledge + Fact Intelligence"
echo
