from __future__ import annotations

from grantbot.core.database import connection


CATEGORIES = {
    "IRS_DETERMINATION",
    "ARTICLES_INCORPORATION",
    "BYLAWS",
    "EIN_W9",
    "SAM_UEI",
    "BOARD",
    "POLICY",
    "FINANCIAL",
    "AUDIT",
    "BUDGET",
    "INSURANCE",
    "LICENSE",
    "RESUME_BIO",
    "PROGRAM",
    "PROPERTY_SITE",
    "PARTNERSHIP",
    "LETTER_SUPPORT",
    "VENDOR_QUOTE",
    "OTHER",
}

VERIFICATION_STATES = {"UNVERIFIED", "VERIFIED", "APPROVED", "REJECTED"}
REQUIREMENT_SCOPES = {
    "GENERAL",
    "FEDERAL",
    "STATE",
    "LOCAL",
    "FOUNDATION",
    "CORPORATE",
    "FAITH",
    "IMPACT_CAPITAL",
}


def initialize_vault_schema() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vault_documents_v22 (
                document_id TEXT PRIMARY KEY,
                document_key TEXT NOT NULL,
                version INTEGER NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                media_type TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                object_relative_path TEXT NOT NULL,
                verification_state TEXT NOT NULL DEFAULT 'UNVERIFIED',
                lifecycle_state TEXT NOT NULL DEFAULT 'CANDIDATE',
                is_current INTEGER NOT NULL DEFAULT 0,
                source_reference TEXT NOT NULL,
                effective_date TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL DEFAULT '',
                review_due_date TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                supersedes_document_id TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reviewed_by TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT NOT NULL DEFAULT '',
                review_note TEXT NOT NULL DEFAULT '',
                UNIQUE(document_key, version)
            );

            CREATE INDEX IF NOT EXISTS idx_vault_documents_v22_key
                ON vault_documents_v22(document_key, version DESC);
            CREATE INDEX IF NOT EXISTS idx_vault_documents_v22_category
                ON vault_documents_v22(category, is_current, verification_state);
            CREATE INDEX IF NOT EXISTS idx_vault_documents_v22_sha
                ON vault_documents_v22(sha256);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_documents_v22_current
                ON vault_documents_v22(document_key)
                WHERE is_current=1;

            CREATE TABLE IF NOT EXISTS vault_events_v22 (
                event_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                document_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(document_id)
                    REFERENCES vault_documents_v22(document_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_vault_events_v22_document
                ON vault_events_v22(document_id, created_at, event_id);

            CREATE TABLE IF NOT EXISTS vault_links_v22 (
                link_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                purpose TEXT NOT NULL,
                linked_by TEXT NOT NULL,
                linked_at TEXT NOT NULL,
                UNIQUE(document_id, entity_type, entity_id, purpose),
                FOREIGN KEY(document_id)
                    REFERENCES vault_documents_v22(document_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_vault_links_v22_entity
                ON vault_links_v22(entity_type, entity_id);

            CREATE TABLE IF NOT EXISTS vault_requirements_v22 (
                requirement_id TEXT PRIMARY KEY,
                requirement_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                document_key TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT 'GENERAL',
                required INTEGER NOT NULL DEFAULT 1,
                must_be_approved INTEGER NOT NULL DEFAULT 1,
                max_age_days INTEGER,
                source_reference TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_vault_requirements_v22_scope
                ON vault_requirements_v22(scope, active, category);
            """
        )
