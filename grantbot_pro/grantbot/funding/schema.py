from __future__ import annotations

from grantbot.core.database import connection, initialize_database


FUNDING_SCHEMA = """
CREATE TABLE IF NOT EXISTS funding_source_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_id INTEGER NOT NULL UNIQUE,

    source_key TEXT NOT NULL UNIQUE,

    source_kind TEXT NOT NULL,

    mechanisms_json TEXT NOT NULL,

    applicant_types_json TEXT,

    issue_areas_json TEXT,

    access_methods_json TEXT,

    nonprofit_fit TEXT NOT NULL DEFAULT 'DIRECT',

    requires_investable_entity INTEGER DEFAULT 0,

    requires_legal_review INTEGER DEFAULT 0,

    requires_subscription INTEGER DEFAULT 0,

    search_priority INTEGER DEFAULT 50,

    notes TEXT,

    FOREIGN KEY(source_id)
        REFERENCES funding_sources(id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS funding_source_scopes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_id INTEGER NOT NULL,

    state TEXT,

    county TEXT,

    city TEXT,

    region TEXT,

    nationwide INTEGER DEFAULT 0,

    FOREIGN KEY(source_id)
        REFERENCES funding_sources(id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS funding_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_id INTEGER,

    query_text TEXT NOT NULL,

    lane TEXT,

    geography TEXT,

    status TEXT DEFAULT 'PLANNED',

    metadata_json TEXT,

    created_at TEXT NOT NULL,

    FOREIGN KEY(source_id)
        REFERENCES funding_sources(id)
        ON DELETE SET NULL
);


CREATE TABLE IF NOT EXISTS funding_discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    started_at TEXT NOT NULL,

    finished_at TEXT,

    source_count INTEGER DEFAULT 0,

    query_count INTEGER DEFAULT 0,

    opportunity_count INTEGER DEFAULT 0,

    error_count INTEGER DEFAULT 0,

    metadata_json TEXT
);


CREATE TABLE IF NOT EXISTS funding_discovery_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    run_id INTEGER,

    source_id INTEGER,

    error_type TEXT,

    message TEXT,

    created_at TEXT NOT NULL,

    FOREIGN KEY(run_id)
        REFERENCES funding_discovery_runs(id)
        ON DELETE CASCADE,

    FOREIGN KEY(source_id)
        REFERENCES funding_sources(id)
        ON DELETE SET NULL
);


CREATE TABLE IF NOT EXISTS opportunity_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    opportunity_id INTEGER NOT NULL,

    tag TEXT NOT NULL,

    UNIQUE(opportunity_id, tag),

    FOREIGN KEY(opportunity_id)
        REFERENCES opportunities(id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS investor_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    investor_id INTEGER NOT NULL,

    relationship_stage TEXT DEFAULT 'IDENTIFIED',

    warm_path TEXT,

    last_contact TEXT,

    next_action TEXT,

    next_action_date TEXT,

    notes TEXT,

    updated_at TEXT NOT NULL,

    FOREIGN KEY(investor_id)
        REFERENCES investors(id)
        ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS idx_source_profiles_kind
ON funding_source_profiles(source_kind);

CREATE INDEX IF NOT EXISTS idx_source_profiles_priority
ON funding_source_profiles(search_priority);

CREATE INDEX IF NOT EXISTS idx_funding_scope_state
ON funding_source_scopes(state);

CREATE INDEX IF NOT EXISTS idx_funding_scope_county
ON funding_source_scopes(county);

CREATE INDEX IF NOT EXISTS idx_funding_scope_city
ON funding_source_scopes(city);

CREATE INDEX IF NOT EXISTS idx_funding_query_status
ON funding_queries(status);

CREATE INDEX IF NOT EXISTS idx_opportunity_tags_tag
ON opportunity_tags(tag);
"""


def initialize_funding_schema() -> None:
    initialize_database()
    with connection() as conn:
        conn.executescript(FUNDING_SCHEMA)
