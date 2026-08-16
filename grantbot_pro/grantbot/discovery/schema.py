from __future__ import annotations

from grantbot.core.database import connection


SCHEMA = """
CREATE TABLE IF NOT EXISTS discovery_source_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_id INTEGER NOT NULL,

    page_name TEXT,

    page_type TEXT NOT NULL DEFAULT 'HTML'
        CHECK (
            page_type IN (
                'HTML',
                'RSS',
                'JSON'
            )
        ),

    url TEXT NOT NULL UNIQUE,

    active INTEGER DEFAULT 1,

    respect_robots INTEGER DEFAULT 1,

    max_links INTEGER DEFAULT 100,

    metadata_json TEXT,

    created_at TEXT NOT NULL,

    updated_at TEXT NOT NULL,

    FOREIGN KEY(source_id)
        REFERENCES funding_sources(id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    mode TEXT NOT NULL,

    started_at TEXT NOT NULL,

    finished_at TEXT,

    sources_attempted INTEGER DEFAULT 0,

    queries_attempted INTEGER DEFAULT 0,

    results_seen INTEGER DEFAULT 0,

    opportunities_saved INTEGER DEFAULT 0,

    duplicates_skipped INTEGER DEFAULT 0,

    errors INTEGER DEFAULT 0,

    metadata_json TEXT
);


CREATE TABLE IF NOT EXISTS discovery_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    run_id INTEGER,

    source_key TEXT,

    query_text TEXT,

    event_type TEXT NOT NULL,

    message TEXT,

    metadata_json TEXT,

    created_at TEXT NOT NULL,

    FOREIGN KEY(run_id)
        REFERENCES discovery_runs(id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS opportunity_fingerprints (
    opportunity_id INTEGER PRIMARY KEY,

    fingerprint TEXT NOT NULL UNIQUE,

    created_at TEXT NOT NULL,

    FOREIGN KEY(opportunity_id)
        REFERENCES opportunities(id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS discovery_page_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    url TEXT NOT NULL UNIQUE,

    title TEXT,

    content_type TEXT,

    status_code INTEGER,

    sha256 TEXT,

    fetched_at TEXT NOT NULL,

    metadata_json TEXT
);


CREATE INDEX IF NOT EXISTS idx_discovery_pages_source
ON discovery_source_pages(source_id);

CREATE INDEX IF NOT EXISTS idx_discovery_runs_started
ON discovery_runs(started_at);

CREATE INDEX IF NOT EXISTS idx_discovery_events_run
ON discovery_events(run_id);

CREATE INDEX IF NOT EXISTS idx_discovery_events_source
ON discovery_events(source_key);
"""


def initialize_discovery_schema() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)
