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
