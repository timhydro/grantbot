#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${HOME}/grantbot_pro"
PYTHON="${ROOT}/.venv/bin/python"

echo
echo "=============================================================="
echo " GRANTBOT PRO"
echo " MODULE 03 — UNIVERSAL FUNDING + INVESTOR INTELLIGENCE"
echo "=============================================================="
echo

# ==============================================================
# PREREQUISITES
# ==============================================================

if [ ! -f "$ROOT/grantbot/core/database.py" ]; then
    echo "ERROR: Module 01 Core is missing."
    exit 1
fi

if [ ! -f "$ROOT/grantbot/knowledge/repository.py" ]; then
    echo "ERROR: Module 02 Knowledge Intelligence is missing."
    exit 1
fi

if [ ! -x "$PYTHON" ]; then
    echo "ERROR: GrantBot virtual environment is missing."
    echo
    echo "Run:"
    echo "cd ~/grantbot_pro && bash bootstrap.sh"
    exit 1
fi

mkdir -p \
    "$ROOT/grantbot/funding" \
    "$ROOT/grantbot/investors" \
    "$ROOT/data/funding" \
    "$ROOT/data/investors" \
    "$ROOT/tests"

touch "$ROOT/grantbot/funding/__init__.py"
touch "$ROOT/grantbot/investors/__init__.py"

# ==============================================================
# FUNDING TYPE SYSTEM
# ==============================================================

cat > "$ROOT/grantbot/funding/types.py" <<'PY'
from __future__ import annotations

from enum import Enum


class Jurisdiction(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    COUNTY = "COUNTY"
    CITY = "CITY"
    MUNICIPAL = "MUNICIPAL"
    REGIONAL = "REGIONAL"
    LOCAL = "LOCAL"
    NATIONAL = "NATIONAL"
    PRIVATE = "PRIVATE"
    INTERNATIONAL = "INTERNATIONAL"


class SourceKind(str, Enum):
    GOVERNMENT = "GOVERNMENT"
    FOUNDATION = "FOUNDATION"
    COMMUNITY_FOUNDATION = "COMMUNITY_FOUNDATION"
    FAMILY_FOUNDATION = "FAMILY_FOUNDATION"
    CORPORATE = "CORPORATE"
    BANK = "BANK"
    CDFI = "CDFI"
    FAITH_BASED = "FAITH_BASED"
    CHURCH = "CHURCH"
    ANGEL_NETWORK = "ANGEL_NETWORK"
    ANGEL_INVESTOR = "ANGEL_INVESTOR"
    IMPACT_INVESTOR = "IMPACT_INVESTOR"
    IMPACT_FUND = "IMPACT_FUND"
    PHILANTHROPIC_INVESTOR = "PHILANTHROPIC_INVESTOR"
    COMMUNITY_REDEVELOPMENT = "COMMUNITY_REDEVELOPMENT"
    CONTINUUM_OF_CARE = "CONTINUUM_OF_CARE"
    WORKFORCE_BOARD = "WORKFORCE_BOARD"
    ECONOMIC_DEVELOPMENT = "ECONOMIC_DEVELOPMENT"
    SPONSOR = "SPONSOR"
    OTHER = "OTHER"


class FundingMechanism(str, Enum):
    GRANT = "GRANT"
    GENERAL_OPERATING = "GENERAL_OPERATING"
    PROGRAM_GRANT = "PROGRAM_GRANT"
    CAPITAL_GRANT = "CAPITAL_GRANT"
    CONSTRUCTION = "CONSTRUCTION"
    LAND_PROPERTY = "LAND_PROPERTY"
    EQUIPMENT = "EQUIPMENT"
    HOUSING = "HOUSING"
    REENTRY = "REENTRY"
    HOMELESSNESS = "HOMELESSNESS"
    WORKFORCE = "WORKFORCE"
    COMMUNITY_DEVELOPMENT = "COMMUNITY_DEVELOPMENT"
    ECONOMIC_DEVELOPMENT = "ECONOMIC_DEVELOPMENT"
    MATCHING_GRANT = "MATCHING_GRANT"
    CHALLENGE_GRANT = "CHALLENGE_GRANT"
    SPONSORSHIP = "SPONSORSHIP"
    IN_KIND = "IN_KIND"
    PROGRAM_RELATED_INVESTMENT = "PROGRAM_RELATED_INVESTMENT"
    IMPACT_INVESTMENT = "IMPACT_INVESTMENT"
    EQUITY_INVESTMENT = "EQUITY_INVESTMENT"
    RECOVERABLE_GRANT = "RECOVERABLE_GRANT"
    FORGIVABLE_FINANCING = "FORGIVABLE_FINANCING"
    LOW_INTEREST_LOAN = "LOW_INTEREST_LOAN"
    LOAN = "LOAN"
    TAX_CREDIT = "TAX_CREDIT"
    CONTRACT = "CONTRACT"
    PROCUREMENT = "PROCUREMENT"
    DONATION = "DONATION"
    OTHER = "OTHER"


class NonprofitFit(str, Enum):
    DIRECT = "DIRECT"
    CONDITIONAL = "CONDITIONAL"
    INDIRECT = "INDIRECT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AccessMethod(str, Enum):
    API = "API"
    WEB = "WEB"
    SEARCH = "SEARCH"
    FEED = "FEED"
    EMAIL = "EMAIL"
    PORTAL = "PORTAL"
    MANUAL = "MANUAL"
    PARTNER_REFERRAL = "PARTNER_REFERRAL"
PY

# ==============================================================
# FUNDING REGISTRY DATABASE SCHEMA
# ==============================================================

cat > "$ROOT/grantbot/funding/schema.py" <<'PY'
from __future__ import annotations

from grantbot.core.database import connection


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
    with connection() as conn:
        conn.executescript(
            FUNDING_SCHEMA
        )
PY

# ==============================================================
# MASTER SOURCE CATALOG
# ==============================================================

cat > "$ROOT/grantbot/funding/catalog.py" <<'PY'
from __future__ import annotations


SOURCE_CATALOG = [

    # ==========================================================
    # FEDERAL
    # ==========================================================

    {
        "source_key": "federal_grants_gov",
        "source_name": "Grants.gov",
        "source_kind": "GOVERNMENT",
        "jurisdiction": "FEDERAL",
        "geography": "United States",
        "website": "https://www.grants.gov",
        "mechanisms": [
            "GRANT",
            "PROGRAM_GRANT",
            "CAPITAL_GRANT",
            "CONSTRUCTION",
            "HOUSING",
            "REENTRY",
            "HOMELESSNESS",
            "WORKFORCE",
            "COMMUNITY_DEVELOPMENT",
        ],
        "issue_areas": [
            "reentry",
            "housing",
            "homelessness",
            "workforce",
            "justice",
            "community development",
            "economic opportunity",
        ],
        "access_methods": [
            "API",
            "WEB",
            "PORTAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 100,
    },

    {
        "source_key": "federal_agency_direct",
        "source_name": "Federal Agency Funding Portals",
        "source_kind": "GOVERNMENT",
        "jurisdiction": "FEDERAL",
        "geography": "United States",
        "mechanisms": [
            "GRANT",
            "CONTRACT",
            "PROCUREMENT",
            "COOPERATIVE_AGREEMENT"
            if False else "OTHER",
        ],
        "issue_areas": [
            "housing",
            "justice",
            "reentry",
            "workforce",
            "community development",
            "homelessness",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PORTAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 95,
    },

    # ==========================================================
    # STATE
    # ==========================================================

    {
        "source_key": "florida_state_agencies",
        "source_name": "Florida State Agency Funding",
        "source_kind": "GOVERNMENT",
        "jurisdiction": "STATE",
        "geography": "Florida",
        "mechanisms": [
            "GRANT",
            "PROGRAM_GRANT",
            "CAPITAL_GRANT",
            "HOUSING",
            "REENTRY",
            "HOMELESSNESS",
            "WORKFORCE",
            "COMMUNITY_DEVELOPMENT",
            "ECONOMIC_DEVELOPMENT",
            "CONTRACT",
        ],
        "issue_areas": [
            "Florida",
            "housing",
            "reentry",
            "homelessness",
            "workforce",
            "community development",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PORTAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 100,
    },

    {
        "source_key": "florida_housing",
        "source_name": "Florida Housing Funding",
        "source_kind": "GOVERNMENT",
        "jurisdiction": "STATE",
        "geography": "Florida",
        "mechanisms": [
            "HOUSING",
            "CAPITAL_GRANT",
            "CONSTRUCTION",
            "LAND_PROPERTY",
            "LOW_INTEREST_LOAN",
            "TAX_CREDIT",
        ],
        "issue_areas": [
            "affordable housing",
            "supportive housing",
            "homelessness",
            "housing development",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PORTAL",
        ],
        "nonprofit_fit": "CONDITIONAL",
        "requires_legal_review": True,
        "search_priority": 100,
    },

    {
        "source_key": "florida_workforce",
        "source_name": "Florida Workforce Funding",
        "source_kind": "WORKFORCE_BOARD",
        "jurisdiction": "STATE",
        "geography": "Florida",
        "mechanisms": [
            "WORKFORCE",
            "PROGRAM_GRANT",
            "CONTRACT",
        ],
        "issue_areas": [
            "employment",
            "job training",
            "workforce development",
            "returning citizens",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 95,
    },

    # ==========================================================
    # COUNTY
    # ==========================================================

    {
        "source_key": "florida_counties",
        "source_name": "Florida County Government Funding",
        "source_kind": "GOVERNMENT",
        "jurisdiction": "COUNTY",
        "geography": "Florida",
        "mechanisms": [
            "GRANT",
            "PROGRAM_GRANT",
            "CAPITAL_GRANT",
            "COMMUNITY_DEVELOPMENT",
            "HOUSING",
            "HOMELESSNESS",
            "WORKFORCE",
            "CONTRACT",
            "PROCUREMENT",
        ],
        "issue_areas": [
            "county grants",
            "human services",
            "housing",
            "homelessness",
            "reentry",
            "community development",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PORTAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 100,
    },

    # ==========================================================
    # CITY / MUNICIPAL
    # ==========================================================

    {
        "source_key": "florida_cities",
        "source_name": "Florida City and Municipal Funding",
        "source_kind": "GOVERNMENT",
        "jurisdiction": "CITY",
        "geography": "Florida",
        "mechanisms": [
            "GRANT",
            "PROGRAM_GRANT",
            "COMMUNITY_DEVELOPMENT",
            "ECONOMIC_DEVELOPMENT",
            "HOUSING",
            "CAPITAL_GRANT",
            "CONTRACT",
        ],
        "issue_areas": [
            "municipal grants",
            "housing",
            "community development",
            "economic development",
            "human services",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PORTAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 100,
    },

    # ==========================================================
    # COMMUNITY REDEVELOPMENT
    # ==========================================================

    {
        "source_key": "florida_cra",
        "source_name": "Florida Community Redevelopment Agencies",
        "source_kind": "COMMUNITY_REDEVELOPMENT",
        "jurisdiction": "LOCAL",
        "geography": "Florida",
        "mechanisms": [
            "COMMUNITY_DEVELOPMENT",
            "ECONOMIC_DEVELOPMENT",
            "CAPITAL_GRANT",
            "LAND_PROPERTY",
            "CONSTRUCTION",
            "GRANT",
        ],
        "issue_areas": [
            "redevelopment",
            "economic development",
            "property",
            "community revitalization",
            "housing",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "CONDITIONAL",
        "search_priority": 95,
    },

    # ==========================================================
    # HOMELESSNESS / CONTINUUM OF CARE
    # ==========================================================

    {
        "source_key": "continuum_of_care",
        "source_name": "Continuum of Care and Homelessness Funding",
        "source_kind": "CONTINUUM_OF_CARE",
        "jurisdiction": "REGIONAL",
        "geography": "Florida",
        "mechanisms": [
            "HOMELESSNESS",
            "HOUSING",
            "PROGRAM_GRANT",
            "GRANT",
        ],
        "issue_areas": [
            "homelessness",
            "supportive housing",
            "rapid rehousing",
            "housing stability",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 100,
    },

    # ==========================================================
    # FOUNDATIONS
    # ==========================================================

    {
        "source_key": "community_foundations",
        "source_name": "Community Foundations",
        "source_kind": "COMMUNITY_FOUNDATION",
        "jurisdiction": "LOCAL",
        "geography": "Florida",
        "mechanisms": [
            "GRANT",
            "PROGRAM_GRANT",
            "GENERAL_OPERATING",
            "CAPITAL_GRANT",
            "MATCHING_GRANT",
        ],
        "issue_areas": [
            "local impact",
            "housing",
            "reentry",
            "community development",
            "poverty",
            "workforce",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 100,
    },

    {
        "source_key": "private_foundations",
        "source_name": "Private Foundations",
        "source_kind": "FOUNDATION",
        "jurisdiction": "PRIVATE",
        "geography": "United States",
        "mechanisms": [
            "GRANT",
            "PROGRAM_GRANT",
            "GENERAL_OPERATING",
            "CAPITAL_GRANT",
            "MATCHING_GRANT",
            "CHALLENGE_GRANT",
        ],
        "issue_areas": [
            "housing",
            "reentry",
            "justice reform",
            "homelessness",
            "workforce",
            "community development",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 95,
    },

    {
        "source_key": "family_foundations",
        "source_name": "Family Foundations",
        "source_kind": "FAMILY_FOUNDATION",
        "jurisdiction": "PRIVATE",
        "geography": "United States",
        "mechanisms": [
            "GRANT",
            "PROGRAM_GRANT",
            "GENERAL_OPERATING",
            "CAPITAL_GRANT",
        ],
        "issue_areas": [
            "community",
            "faith",
            "poverty",
            "housing",
            "employment",
            "reentry",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 90,
    },

    # ==========================================================
    # CORPORATE
    # ==========================================================

    {
        "source_key": "corporate_giving",
        "source_name": "Corporate Giving Programs",
        "source_kind": "CORPORATE",
        "jurisdiction": "PRIVATE",
        "geography": "United States",
        "mechanisms": [
            "GRANT",
            "SPONSORSHIP",
            "IN_KIND",
            "PROGRAM_GRANT",
            "EQUIPMENT",
        ],
        "issue_areas": [
            "community impact",
            "workforce",
            "employment",
            "housing",
            "economic mobility",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 90,
    },

    # ==========================================================
    # BANK / CRA
    # ==========================================================

    {
        "source_key": "bank_cra",
        "source_name": "Bank Community Reinvestment Funding",
        "source_kind": "BANK",
        "jurisdiction": "PRIVATE",
        "geography": "Florida",
        "mechanisms": [
            "GRANT",
            "SPONSORSHIP",
            "PROGRAM_RELATED_INVESTMENT",
            "LOW_INTEREST_LOAN",
            "CAPITAL_GRANT",
        ],
        "issue_areas": [
            "low income communities",
            "housing",
            "economic development",
            "workforce",
            "community development",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 100,
    },

    # ==========================================================
    # CDFI
    # ==========================================================

    {
        "source_key": "cdfi",
        "source_name": "Community Development Financial Institutions",
        "source_kind": "CDFI",
        "jurisdiction": "PRIVATE",
        "geography": "United States",
        "mechanisms": [
            "LOW_INTEREST_LOAN",
            "LOAN",
            "PROGRAM_RELATED_INVESTMENT",
            "CAPITAL_GRANT",
            "LAND_PROPERTY",
            "CONSTRUCTION",
        ],
        "issue_areas": [
            "housing",
            "community development",
            "economic development",
            "social enterprise",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "CONDITIONAL",
        "requires_legal_review": True,
        "search_priority": 95,
    },

    # ==========================================================
    # FAITH
    # ==========================================================

    {
        "source_key": "faith_based_funding",
        "source_name": "Faith-Based and Ministry Funding",
        "source_kind": "FAITH_BASED",
        "jurisdiction": "PRIVATE",
        "geography": "United States",
        "mechanisms": [
            "GRANT",
            "PROGRAM_GRANT",
            "GENERAL_OPERATING",
            "CAPITAL_GRANT",
            "DONATION",
            "IN_KIND",
        ],
        "issue_areas": [
            "ministry",
            "restoration",
            "housing",
            "reentry",
            "homelessness",
            "community",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 95,
    },

    {
        "source_key": "church_partnerships",
        "source_name": "Church Partnership Funding",
        "source_kind": "CHURCH",
        "jurisdiction": "LOCAL",
        "geography": "Florida",
        "mechanisms": [
            "DONATION",
            "SPONSORSHIP",
            "IN_KIND",
            "CAPITAL_GRANT",
        ],
        "issue_areas": [
            "ministry",
            "community",
            "reentry",
            "housing",
            "homelessness",
        ],
        "access_methods": [
            "PARTNER_REFERRAL",
            "WEB",
            "MANUAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 90,
    },

    # ==========================================================
    # ANGEL INVESTORS
    # ==========================================================

    {
        "source_key": "angel_investors",
        "source_name": "Angel Investors and Angel Networks",
        "source_kind": "ANGEL_NETWORK",
        "jurisdiction": "PRIVATE",
        "geography": "United States",
        "mechanisms": [
            "EQUITY_INVESTMENT",
            "IMPACT_INVESTMENT",
        ],
        "issue_areas": [
            "social enterprise",
            "housing innovation",
            "workforce innovation",
            "impact ventures",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "INDIRECT",
        "requires_investable_entity": True,
        "requires_legal_review": True,
        "search_priority": 75,
        "notes":
            "Equity investment generally requires an "
            "appropriate investable entity or affiliated "
            "social enterprise. Do not treat angel capital "
            "as ordinary nonprofit grant revenue.",
    },

    # ==========================================================
    # IMPACT INVESTORS
    # ==========================================================

    {
        "source_key": "impact_investors",
        "source_name": "Impact Investors",
        "source_kind": "IMPACT_INVESTOR",
        "jurisdiction": "PRIVATE",
        "geography": "United States",
        "mechanisms": [
            "IMPACT_INVESTMENT",
            "PROGRAM_RELATED_INVESTMENT",
            "LOW_INTEREST_LOAN",
            "RECOVERABLE_GRANT",
            "EQUITY_INVESTMENT",
        ],
        "issue_areas": [
            "housing",
            "economic mobility",
            "workforce",
            "reentry",
            "social impact",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "CONDITIONAL",
        "requires_legal_review": True,
        "search_priority": 85,
    },

    # ==========================================================
    # PRI
    # ==========================================================

    {
        "source_key": "program_related_investments",
        "source_name": "Program-Related Investments",
        "source_kind": "PHILANTHROPIC_INVESTOR",
        "jurisdiction": "PRIVATE",
        "geography": "United States",
        "mechanisms": [
            "PROGRAM_RELATED_INVESTMENT",
            "LOW_INTEREST_LOAN",
            "RECOVERABLE_GRANT",
        ],
        "issue_areas": [
            "housing",
            "community development",
            "social impact",
            "economic opportunity",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
        ],
        "nonprofit_fit": "CONDITIONAL",
        "requires_legal_review": True,
        "search_priority": 85,
    },

    # ==========================================================
    # IN-KIND / SPONSORSHIP
    # ==========================================================

    {
        "source_key": "sponsorship_in_kind",
        "source_name": "Sponsorship and In-Kind Funding",
        "source_kind": "SPONSOR",
        "jurisdiction": "PRIVATE",
        "geography": "Florida",
        "mechanisms": [
            "SPONSORSHIP",
            "IN_KIND",
            "DONATION",
            "EQUIPMENT",
        ],
        "issue_areas": [
            "construction materials",
            "vehicles",
            "equipment",
            "technology",
            "food",
            "housing",
            "workforce",
        ],
        "access_methods": [
            "WEB",
            "SEARCH",
            "PARTNER_REFERRAL",
            "MANUAL",
        ],
        "nonprofit_fit": "DIRECT",
        "search_priority": 85,
    },
]
PY

# ==============================================================
# SOURCE REGISTRY
# ==============================================================

cat > "$ROOT/grantbot/funding/registry.py" <<'PY'
from __future__ import annotations

import json
from typing import Any

from grantbot.core.database import (
    audit,
    connection,
    fetch_all,
    fetch_one,
    utc_now,
)
from grantbot.core.utils import (
    safe_json_dumps,
    safe_json_loads,
)
from grantbot.funding.catalog import SOURCE_CATALOG
from grantbot.funding.schema import initialize_funding_schema


def _bool(value) -> int:
    return 1 if bool(value) else 0


def register_source(
    *,
    source_key: str,
    source_name: str,
    source_kind: str,
    jurisdiction: str,
    geography: str,
    mechanisms: list[str],
    issue_areas: list[str] | None = None,
    access_methods: list[str] | None = None,
    applicant_types: list[str] | None = None,
    website: str | None = None,
    api_endpoint: str | None = None,
    nonprofit_fit: str = "DIRECT",
    requires_investable_entity: bool = False,
    requires_legal_review: bool = False,
    requires_subscription: bool = False,
    search_priority: int = 50,
    notes: str | None = None,
) -> dict[str, Any]:

    initialize_funding_schema()

    source_key = source_key.strip().lower()

    with connection() as conn:
        row = conn.execute(
            """
            SELECT fs.id
            FROM funding_sources fs
            JOIN funding_source_profiles p
              ON p.source_id = fs.id
            WHERE p.source_key=?
            """,
            (source_key,),
        ).fetchone()

        now = utc_now()

        if row:
            source_id = row["id"]

            conn.execute(
                """
                UPDATE funding_sources
                SET
                    source_type=?,
                    source_name=?,
                    jurisdiction_level=?,
                    geography=?,
                    website=?,
                    api_endpoint=?,
                    active=1,
                    updated_at=?
                WHERE id=?
                """,
                (
                    source_kind,
                    source_name,
                    jurisdiction,
                    geography,
                    website,
                    api_endpoint,
                    now,
                    source_id,
                ),
            )

            conn.execute(
                """
                UPDATE funding_source_profiles
                SET
                    source_kind=?,
                    mechanisms_json=?,
                    applicant_types_json=?,
                    issue_areas_json=?,
                    access_methods_json=?,
                    nonprofit_fit=?,
                    requires_investable_entity=?,
                    requires_legal_review=?,
                    requires_subscription=?,
                    search_priority=?,
                    notes=?
                WHERE source_id=?
                """,
                (
                    source_kind,
                    safe_json_dumps(mechanisms),
                    safe_json_dumps(applicant_types or []),
                    safe_json_dumps(issue_areas or []),
                    safe_json_dumps(access_methods or []),
                    nonprofit_fit,
                    _bool(requires_investable_entity),
                    _bool(requires_legal_review),
                    _bool(requires_subscription),
                    int(search_priority),
                    notes,
                    source_id,
                ),
            )

            action = "funding_source.updated"

        else:
            cursor = conn.execute(
                """
                INSERT INTO funding_sources(
                    source_type,
                    source_name,
                    jurisdiction_level,
                    geography,
                    website,
                    api_endpoint,
                    active,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    source_kind,
                    source_name,
                    jurisdiction,
                    geography,
                    website,
                    api_endpoint,
                    "{}",
                    now,
                    now,
                ),
            )

            source_id = cursor.lastrowid

            conn.execute(
                """
                INSERT INTO funding_source_profiles(
                    source_id,
                    source_key,
                    source_kind,
                    mechanisms_json,
                    applicant_types_json,
                    issue_areas_json,
                    access_methods_json,
                    nonprofit_fit,
                    requires_investable_entity,
                    requires_legal_review,
                    requires_subscription,
                    search_priority,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    source_key,
                    source_kind,
                    safe_json_dumps(mechanisms),
                    safe_json_dumps(applicant_types or []),
                    safe_json_dumps(issue_areas or []),
                    safe_json_dumps(access_methods or []),
                    nonprofit_fit,
                    _bool(requires_investable_entity),
                    _bool(requires_legal_review),
                    _bool(requires_subscription),
                    int(search_priority),
                    notes,
                ),
            )

            action = "funding_source.created"

    audit(
        action,
        entity_type="funding_source",
        entity_id=source_id,
        details={
            "source_key": source_key,
            "source_name": source_name,
            "source_kind": source_kind,
        },
    )

    return get_source(
        source_key
    )


def seed_catalog() -> int:
    count = 0

    for source in SOURCE_CATALOG:
        register_source(
            **source
        )

        count += 1

    return count


def get_source(
    source_key: str,
) -> dict[str, Any] | None:

    row = fetch_one(
        """
        SELECT
            fs.*,
            p.source_key,
            p.source_kind,
            p.mechanisms_json,
            p.applicant_types_json,
            p.issue_areas_json,
            p.access_methods_json,
            p.nonprofit_fit,
            p.requires_investable_entity,
            p.requires_legal_review,
            p.requires_subscription,
            p.search_priority,
            p.notes
        FROM funding_sources fs
        JOIN funding_source_profiles p
          ON p.source_id=fs.id
        WHERE p.source_key=?
        """,
        (
            source_key.strip().lower(),
        ),
    )

    return decode_source(
        row
    ) if row else None


def list_sources(
    *,
    active_only: bool = True,
    source_kind: str | None = None,
    jurisdiction: str | None = None,
) -> list[dict[str, Any]]:

    sql = """
        SELECT
            fs.*,
            p.source_key,
            p.source_kind,
            p.mechanisms_json,
            p.applicant_types_json,
            p.issue_areas_json,
            p.access_methods_json,
            p.nonprofit_fit,
            p.requires_investable_entity,
            p.requires_legal_review,
            p.requires_subscription,
            p.search_priority,
            p.notes
        FROM funding_sources fs
        JOIN funding_source_profiles p
          ON p.source_id=fs.id
        WHERE 1=1
    """

    params: list[Any] = []

    if active_only:
        sql += """
            AND fs.active=1
        """

    if source_kind:
        sql += """
            AND p.source_kind=?
        """
        params.append(
            source_kind.upper()
        )

    if jurisdiction:
        sql += """
            AND fs.jurisdiction_level=?
        """
        params.append(
            jurisdiction.upper()
        )

    sql += """
        ORDER BY
            p.search_priority DESC,
            fs.source_name
    """

    rows = fetch_all(
        sql,
        tuple(params),
    )

    return [
        decode_source(row)
        for row in rows
    ]


def decode_source(
    row: dict[str, Any],
) -> dict[str, Any]:

    result = dict(row)

    for field in (
        "mechanisms_json",
        "applicant_types_json",
        "issue_areas_json",
        "access_methods_json",
        "metadata_json",
    ):
        target = field.removesuffix(
            "_json"
        )

        result[target] = safe_json_loads(
            result.get(field),
            [] if field != "metadata_json"
            else {},
        )

    return result


def registry_stats() -> dict[str, Any]:
    sources = list_sources()

    by_kind: dict[str, int] = {}
    by_jurisdiction: dict[str, int] = {}
    mechanisms: dict[str, int] = {}

    for source in sources:
        kind = source["source_kind"]

        by_kind[kind] = (
            by_kind.get(kind, 0)
            + 1
        )

        jurisdiction = (
            source.get(
                "jurisdiction_level"
            )
            or "UNKNOWN"
        )

        by_jurisdiction[jurisdiction] = (
            by_jurisdiction.get(
                jurisdiction,
                0,
            )
            + 1
        )

        for mechanism in source.get(
            "mechanisms",
            [],
        ):
            mechanisms[mechanism] = (
                mechanisms.get(
                    mechanism,
                    0,
                )
                + 1
            )

    return {
        "total_sources":
            len(sources),

        "by_kind":
            dict(
                sorted(
                    by_kind.items()
                )
            ),

        "by_jurisdiction":
            dict(
                sorted(
                    by_jurisdiction.items()
                )
            ),

        "funding_mechanisms":
            dict(
                sorted(
                    mechanisms.items()
                )
            ),
    }
PY

# ==============================================================
# INVESTOR LEGAL / STRUCTURE GUARD
# ==============================================================

cat > "$ROOT/grantbot/investors/structure_guard.py" <<'PY'
from __future__ import annotations


EQUITY_MECHANISMS = {
    "EQUITY_INVESTMENT",
}


RETURN_BEARING = {
    "EQUITY_INVESTMENT",
    "IMPACT_INVESTMENT",
    "PROGRAM_RELATED_INVESTMENT",
    "LOW_INTEREST_LOAN",
    "LOAN",
    "RECOVERABLE_GRANT",
}


def analyze_source_structure(
    source: dict,
) -> dict:

    mechanisms = set(
        source.get(
            "mechanisms",
            [],
        )
    )

    warnings = []

    requires_entity = bool(
        source.get(
            "requires_investable_entity"
        )
    )

    requires_review = bool(
        source.get(
            "requires_legal_review"
        )
    )

    if mechanisms & EQUITY_MECHANISMS:
        warnings.append(
            "Equity investment must not be treated as "
            "ordinary nonprofit grant revenue. Confirm "
            "the legal entity and investment structure "
            "before pursuing or promising equity."
        )

        requires_entity = True
        requires_review = True

    if mechanisms & RETURN_BEARING:
        warnings.append(
            "Return-bearing capital requires financial, "
            "governance, tax, and legal review before "
            "terms are represented to a funder or investor."
        )

        requires_review = True

    return {
        "source_key":
            source.get(
                "source_key"
            ),

        "direct_nonprofit_fit":
            source.get(
                "nonprofit_fit"
            )
            == "DIRECT",

        "requires_investable_entity":
            requires_entity,

        "requires_legal_review":
            requires_review,

        "warnings":
            warnings,
    }
PY

# ==============================================================
# FUNDING SEARCH LANES
# ==============================================================

cat > "$ROOT/grantbot/funding/lanes.py" <<'PY'
from __future__ import annotations


SEARCH_LANES = {

    "reentry": [
        "reentry",
        "returning citizens",
        "justice involved",
        "post incarceration",
        "prison reentry",
        "jail reentry",
        "second chance",
    ],

    "housing": [
        "affordable housing",
        "supportive housing",
        "tiny homes",
        "housing stability",
        "transitional housing",
        "permanent housing",
        "housing development",
    ],

    "homelessness": [
        "homelessness",
        "homeless services",
        "rapid rehousing",
        "housing first",
        "unsheltered homelessness",
        "continuum of care",
    ],

    "workforce": [
        "workforce development",
        "job training",
        "employment services",
        "occupational training",
        "career pathways",
        "returning citizen employment",
    ],

    "community_development": [
        "community development",
        "neighborhood revitalization",
        "community revitalization",
        "economic opportunity",
        "low income communities",
    ],

    "capital": [
        "capital grant",
        "construction grant",
        "property acquisition",
        "land acquisition",
        "facility development",
        "equipment grant",
    ],

    "economic_development": [
        "economic development",
        "social enterprise",
        "job creation",
        "economic mobility",
        "community wealth",
    ],

    "foundation": [
        "foundation grant",
        "community foundation",
        "family foundation",
        "general operating support",
        "capacity building",
    ],

    "faith": [
        "faith based grant",
        "ministry grant",
        "church foundation",
        "Christian foundation",
        "community ministry funding",
    ],

    "corporate": [
        "corporate giving",
        "corporate foundation",
        "community investment",
        "corporate sponsorship",
        "in kind donation",
    ],

    "bank_cra": [
        "community reinvestment",
        "CRA grant",
        "bank foundation",
        "community development finance",
        "low income community investment",
    ],

    "investor": [
        "impact investor",
        "angel investor",
        "social impact investment",
        "program related investment",
        "recoverable grant",
        "mission investment",
    ],
}


DEFAULT_PRIORITY_LANES = [
    "reentry",
    "housing",
    "homelessness",
    "workforce",
    "community_development",
    "capital",
    "economic_development",
    "foundation",
    "faith",
    "corporate",
    "bank_cra",
    "investor",
]
PY

# ==============================================================
# INTELLIGENT QUERY PLANNER
# ==============================================================

cat > "$ROOT/grantbot/funding/planner.py" <<'PY'
from __future__ import annotations

from itertools import product

from grantbot.core.database import (
    connection,
    utc_now,
)

from grantbot.core.utils import (
    safe_json_dumps,
)

from grantbot.funding.lanes import (
    DEFAULT_PRIORITY_LANES,
    SEARCH_LANES,
)

from grantbot.funding.registry import (
    list_sources,
)

from grantbot.investors.structure_guard import (
    analyze_source_structure,
)


LANE_SOURCE_MAP = {

    "reentry": {
        "GOVERNMENT",
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "FAMILY_FOUNDATION",
        "FAITH_BASED",
        "WORKFORCE_BOARD",
    },

    "housing": {
        "GOVERNMENT",
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "BANK",
        "CDFI",
        "COMMUNITY_REDEVELOPMENT",
        "CONTINUUM_OF_CARE",
        "IMPACT_INVESTOR",
        "PHILANTHROPIC_INVESTOR",
    },

    "homelessness": {
        "GOVERNMENT",
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "FAITH_BASED",
        "CONTINUUM_OF_CARE",
    },

    "workforce": {
        "GOVERNMENT",
        "WORKFORCE_BOARD",
        "FOUNDATION",
        "CORPORATE",
        "BANK",
        "IMPACT_INVESTOR",
    },

    "community_development": {
        "GOVERNMENT",
        "COMMUNITY_REDEVELOPMENT",
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "BANK",
        "CDFI",
        "IMPACT_INVESTOR",
    },

    "capital": {
        "GOVERNMENT",
        "FOUNDATION",
        "BANK",
        "CDFI",
        "FAITH_BASED",
        "CHURCH",
        "SPONSOR",
        "IMPACT_INVESTOR",
        "PHILANTHROPIC_INVESTOR",
    },

    "economic_development": {
        "GOVERNMENT",
        "COMMUNITY_REDEVELOPMENT",
        "BANK",
        "CDFI",
        "CORPORATE",
        "IMPACT_INVESTOR",
        "ANGEL_NETWORK",
    },

    "foundation": {
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "FAMILY_FOUNDATION",
    },

    "faith": {
        "FAITH_BASED",
        "CHURCH",
    },

    "corporate": {
        "CORPORATE",
        "SPONSOR",
    },

    "bank_cra": {
        "BANK",
        "CDFI",
    },

    "investor": {
        "ANGEL_NETWORK",
        "ANGEL_INVESTOR",
        "IMPACT_INVESTOR",
        "IMPACT_FUND",
        "PHILANTHROPIC_INVESTOR",
    },
}


def _source_matches_lane(
    source: dict,
    lane: str,
) -> bool:

    allowed = LANE_SOURCE_MAP.get(
        lane
    )

    if not allowed:
        return True

    return (
        source.get(
            "source_kind"
        )
        in allowed
    )


def build_discovery_plan(
    *,
    state: str = "Florida",
    counties: list[str] | None = None,
    cities: list[str] | None = None,
    lanes: list[str] | None = None,
    max_terms_per_lane: int = 4,
) -> list[dict]:

    counties = [
        c.strip()
        for c in (
            counties or []
        )
        if c.strip()
    ]

    cities = [
        c.strip()
        for c in (
            cities or []
        )
        if c.strip()
    ]

    lanes = (
        lanes
        or DEFAULT_PRIORITY_LANES
    )

    sources = list_sources()

    plan = []

    for lane in lanes:

        terms = SEARCH_LANES.get(
            lane,
            []
        )[:max_terms_per_lane]

        for source in sources:

            if not _source_matches_lane(
                source,
                lane,
            ):
                continue

            jurisdiction = (
                source.get(
                    "jurisdiction_level"
                )
                or ""
            )

            geographies = []

            if jurisdiction == "COUNTY":
                geographies = [
                    f"{county} County, {state}"
                    for county in counties
                ]

                if not geographies:
                    geographies = [
                        state
                    ]

            elif jurisdiction in {
                "CITY",
                "MUNICIPAL",
            }:
                geographies = [
                    f"{city}, {state}"
                    for city in cities
                ]

                if not geographies:
                    geographies = [
                        state
                    ]

            elif jurisdiction in {
                "STATE",
                "LOCAL",
                "REGIONAL",
            }:
                geographies = [
                    state
                ]

            else:
                geographies = [
                    source.get(
                        "geography"
                    )
                    or state
                ]

            structure = (
                analyze_source_structure(
                    source
                )
            )

            for term, geography in product(
                terms,
                geographies,
            ):
                query = (
                    f"{term} "
                    f"{geography}"
                ).strip()

                plan.append({
                    "source_id":
                        source["id"],

                    "source_key":
                        source[
                            "source_key"
                        ],

                    "source_name":
                        source[
                            "source_name"
                        ],

                    "source_kind":
                        source[
                            "source_kind"
                        ],

                    "jurisdiction":
                        jurisdiction,

                    "lane":
                        lane,

                    "query":
                        query,

                    "geography":
                        geography,

                    "priority":
                        source.get(
                            "search_priority",
                            50,
                        ),

                    "nonprofit_fit":
                        source.get(
                            "nonprofit_fit"
                        ),

                    "requires_legal_review":
                        structure[
                            "requires_legal_review"
                        ],

                    "requires_investable_entity":
                        structure[
                            "requires_investable_entity"
                        ],

                    "warnings":
                        structure[
                            "warnings"
                        ],
                })

    plan.sort(
        key=lambda row: (
            -row["priority"],
            row[
                "requires_legal_review"
            ],
            row["lane"],
            row["source_name"],
            row["query"],
        )
    )

    return plan


def save_plan(
    plan: list[dict],
) -> int:

    with connection() as conn:

        conn.execute(
            """
            DELETE FROM funding_queries
            WHERE status='PLANNED'
            """
        )

        for row in plan:
            conn.execute(
                """
                INSERT INTO funding_queries(
                    source_id,
                    query_text,
                    lane,
                    geography,
                    status,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, 'PLANNED', ?, ?)
                """,
                (
                    row["source_id"],
                    row["query"],
                    row["lane"],
                    row["geography"],
                    safe_json_dumps({
                        "priority":
                            row[
                                "priority"
                            ],

                        "source_key":
                            row[
                                "source_key"
                            ],

                        "nonprofit_fit":
                            row[
                                "nonprofit_fit"
                            ],

                        "requires_legal_review":
                            row[
                                "requires_legal_review"
                            ],

                        "requires_investable_entity":
                            row[
                                "requires_investable_entity"
                            ],

                        "warnings":
                            row[
                                "warnings"
                            ],
                    }),
                    utc_now(),
                ),
            )

    return len(plan)
PY

# ==============================================================
# SOURCE-LEVEL PRECHECK
# ==============================================================

cat > "$ROOT/grantbot/funding/precheck.py" <<'PY'
from __future__ import annotations

from grantbot.investors.structure_guard import (
    analyze_source_structure,
)


def precheck_source(
    source: dict,
) -> dict:

    score = 100
    blockers = []
    warnings = []

    fit = source.get(
        "nonprofit_fit",
        "DIRECT",
    )

    if fit == "DIRECT":
        pass

    elif fit == "CONDITIONAL":
        score -= 15

        warnings.append(
            "Funding source is conditionally compatible "
            "with nonprofit applicants. Verify the "
            "specific program requirements."
        )

    elif fit == "INDIRECT":
        score -= 35

        warnings.append(
            "Funding source is not ordinarily direct "
            "nonprofit grant funding."
        )

    elif fit == "NOT_APPLICABLE":
        score = 0

        blockers.append(
            "Source is not applicable to the "
            "organization's current structure."
        )

    structure = (
        analyze_source_structure(
            source
        )
    )

    warnings.extend(
        structure[
            "warnings"
        ]
    )

    if structure[
        "requires_investable_entity"
    ]:
        score -= 20

        warnings.append(
            "Confirm that an appropriate investable "
            "entity or affiliated social enterprise "
            "exists before treating this as viable."
        )

    if structure[
        "requires_legal_review"
    ]:
        warnings.append(
            "Legal/tax/financial structure review is "
            "required before commitments are made."
        )

    score = max(
        0,
        min(
            100,
            score,
        ),
    )

    return {
        "score":
            score,

        "direct_fit":
            fit == "DIRECT",

        "eligible_to_investigate":
            score > 0,

        "blockers":
            blockers,

        "warnings":
            list(
                dict.fromkeys(
                    warnings
                )
            ),
    }
PY

# ==============================================================
# OPPORTUNITY NORMALIZER / INGESTER
# ==============================================================

cat > "$ROOT/grantbot/funding/ingest.py" <<'PY'
from __future__ import annotations

import json
from typing import Any

from grantbot.core.database import (
    audit,
    connection,
    utc_now,
)

from grantbot.core.utils import (
    normalize_text,
    safe_json_dumps,
)

from grantbot.funding.registry import (
    get_source,
)


def normalize_opportunity(
    payload: dict[str, Any],
) -> dict[str, Any]:

    title = normalize_text(
        payload.get(
            "title"
        )
    )

    if not title:
        raise ValueError(
            "Opportunity requires a title."
        )

    return {
        "external_id":
            normalize_text(
                payload.get(
                    "external_id"
                )
            )
            or None,

        "opportunity_type":
            normalize_text(
                payload.get(
                    "opportunity_type"
                )
            ).upper()
            or "GRANT",

        "title":
            title,

        "funder":
            normalize_text(
                payload.get(
                    "funder"
                )
            )
            or None,

        "agency":
            normalize_text(
                payload.get(
                    "agency"
                )
            )
            or None,

        "description":
            normalize_text(
                payload.get(
                    "description"
                )
            )
            or None,

        "eligibility":
            normalize_text(
                payload.get(
                    "eligibility"
                )
            )
            or None,

        "geography":
            normalize_text(
                payload.get(
                    "geography"
                )
            )
            or None,

        "opening_date":
            normalize_text(
                payload.get(
                    "opening_date"
                )
            )
            or None,

        "deadline":
            normalize_text(
                payload.get(
                    "deadline"
                )
            )
            or None,

        "award_floor":
            payload.get(
                "award_floor"
            ),

        "award_ceiling":
            payload.get(
                "award_ceiling"
            ),

        "estimated_total":
            payload.get(
                "estimated_total"
            ),

        "opportunity_number":
            normalize_text(
                payload.get(
                    "opportunity_number"
                )
            )
            or None,

        "assistance_listing":
            normalize_text(
                payload.get(
                    "assistance_listing"
                )
            )
            or None,

        "source_url":
            normalize_text(
                payload.get(
                    "source_url"
                )
            )
            or None,

        "status":
            normalize_text(
                payload.get(
                    "status"
                )
            ).upper()
            or "DISCOVERED",

        "raw_json":
            safe_json_dumps(
                payload
            ),
    }


def ingest_opportunity(
    source_key: str,
    payload: dict[str, Any],
) -> int:

    source = get_source(
        source_key
    )

    if not source:
        raise ValueError(
            f"Unknown funding source: "
            f"{source_key}"
        )

    row = normalize_opportunity(
        payload
    )

    now = utc_now()

    with connection() as conn:

        existing = None

        if row["external_id"]:
            existing = conn.execute(
                """
                SELECT id
                FROM opportunities
                WHERE
                    external_id=?
                    AND funding_source_id=?
                """,
                (
                    row[
                        "external_id"
                    ],
                    source["id"],
                ),
            ).fetchone()

        if existing:

            opportunity_id = (
                existing["id"]
            )

            conn.execute(
                """
                UPDATE opportunities
                SET
                    opportunity_type=?,
                    title=?,
                    funder=?,
                    agency=?,
                    description=?,
                    eligibility=?,
                    geography=?,
                    opening_date=?,
                    deadline=?,
                    award_floor=?,
                    award_ceiling=?,
                    estimated_total=?,
                    opportunity_number=?,
                    assistance_listing=?,
                    source_url=?,
                    status=?,
                    raw_json=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    row[
                        "opportunity_type"
                    ],
                    row["title"],
                    row["funder"],
                    row["agency"],
                    row[
                        "description"
                    ],
                    row[
                        "eligibility"
                    ],
                    row[
                        "geography"
                    ],
                    row[
                        "opening_date"
                    ],
                    row[
                        "deadline"
                    ],
                    row[
                        "award_floor"
                    ],
                    row[
                        "award_ceiling"
                    ],
                    row[
                        "estimated_total"
                    ],
                    row[
                        "opportunity_number"
                    ],
                    row[
                        "assistance_listing"
                    ],
                    row[
                        "source_url"
                    ],
                    row["status"],
                    row[
                        "raw_json"
                    ],
                    now,
                    opportunity_id,
                ),
            )

            action = (
                "opportunity.updated"
            )

        else:

            cursor = conn.execute(
                """
                INSERT INTO opportunities(
                    external_id,
                    funding_source_id,
                    opportunity_type,
                    title,
                    funder,
                    agency,
                    description,
                    eligibility,
                    geography,
                    opening_date,
                    deadline,
                    award_floor,
                    award_ceiling,
                    estimated_total,
                    opportunity_number,
                    assistance_listing,
                    source_url,
                    status,
                    raw_json,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    row[
                        "external_id"
                    ],
                    source["id"],
                    row[
                        "opportunity_type"
                    ],
                    row["title"],
                    row["funder"],
                    row["agency"],
                    row[
                        "description"
                    ],
                    row[
                        "eligibility"
                    ],
                    row[
                        "geography"
                    ],
                    row[
                        "opening_date"
                    ],
                    row[
                        "deadline"
                    ],
                    row[
                        "award_floor"
                    ],
                    row[
                        "award_ceiling"
                    ],
                    row[
                        "estimated_total"
                    ],
                    row[
                        "opportunity_number"
                    ],
                    row[
                        "assistance_listing"
                    ],
                    row[
                        "source_url"
                    ],
                    row[
                        "status"
                    ],
                    row[
                        "raw_json"
                    ],
                    now,
                    now,
                ),
            )

            opportunity_id = (
                cursor.lastrowid
            )

            action = (
                "opportunity.created"
            )

    audit(
        action,
        entity_type="opportunity",
        entity_id=opportunity_id,
        details={
            "source_key":
                source_key,

            "title":
                row["title"],
        },
    )

    return int(
        opportunity_id
    )
PY

# ==============================================================
# BASE CONNECTOR ARCHITECTURE
# ==============================================================

cat > "$ROOT/grantbot/funding/adapters.py" <<'PY'
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class SearchRequest:
    query: str

    geography: str | None = None

    limit: int = 25

    filters: dict[str, Any] | None = None


@dataclass
class SearchResult:
    external_id: str | None

    title: str

    description: str | None = None

    eligibility: str | None = None

    funder: str | None = None

    agency: str | None = None

    geography: str | None = None

    deadline: str | None = None

    award_floor: float | None = None

    award_ceiling: float | None = None

    source_url: str | None = None

    raw: dict[str, Any] | None = None


class FundingSourceAdapter(ABC):
    """
    Common contract for every live funding connector.

    Later modules can implement:
      - Grants.gov
      - state portals
      - county/city searches
      - foundations
      - corporate giving
      - investor discovery

    The rest of GrantBot does not need to know how
    each source is searched.
    """

    source_key: str

    @abstractmethod
    def search(
        self,
        request: SearchRequest,
    ) -> Iterable[SearchResult]:
        raise NotImplementedError


class AdapterRegistry:
    def __init__(self):
        self._adapters = {}

    def register(
        self,
        adapter: FundingSourceAdapter,
    ):
        self._adapters[
            adapter.source_key
        ] = adapter

    def get(
        self,
        source_key: str,
    ):
        return self._adapters.get(
            source_key
        )

    def keys(self):
        return sorted(
            self._adapters
        )


ADAPTERS = AdapterRegistry()
PY

# ==============================================================
# FUNDING INTELLIGENCE SERVICE
# ==============================================================

cat > "$ROOT/grantbot/funding/service.py" <<'PY'
from __future__ import annotations

from grantbot.funding.planner import (
    build_discovery_plan,
)
from grantbot.funding.precheck import (
    precheck_source,
)
from grantbot.funding.registry import (
    list_sources,
    registry_stats,
)


def funding_intelligence_summary() -> dict:

    sources = list_sources()

    direct = []
    conditional = []
    investor_related = []

    for source in sources:

        check = precheck_source(
            source
        )

        record = {
            "source_key":
                source[
                    "source_key"
                ],

            "source_name":
                source[
                    "source_name"
                ],

            "source_kind":
                source[
                    "source_kind"
                ],

            "jurisdiction":
                source[
                    "jurisdiction_level"
                ],

            "fit":
                source[
                    "nonprofit_fit"
                ],

            "precheck":
                check,
        }

        if (
            source[
                "source_kind"
            ]
            in {
                "ANGEL_NETWORK",
                "ANGEL_INVESTOR",
                "IMPACT_INVESTOR",
                "IMPACT_FUND",
                "PHILANTHROPIC_INVESTOR",
            }
        ):
            investor_related.append(
                record
            )

        elif source[
            "nonprofit_fit"
        ] == "DIRECT":
            direct.append(
                record
            )

        else:
            conditional.append(
                record
            )

    return {
        "registry":
            registry_stats(),

        "direct_nonprofit_sources":
            direct,

        "conditional_sources":
            conditional,

        "investor_sources":
            investor_related,
    }


def default_plan(
    *,
    counties: list[str] | None = None,
    cities: list[str] | None = None,
):
    return build_discovery_plan(
        state="Florida",
        counties=counties,
        cities=cities,
    )
PY

# ==============================================================
# MODULE CLI
# ==============================================================

cat > "$ROOT/grantbot/funding/cli.py" <<'PY'
from __future__ import annotations

import argparse
import json

from grantbot.core.database import (
    initialize_database,
)

from grantbot.funding.planner import (
    build_discovery_plan,
    save_plan,
)

from grantbot.funding.registry import (
    get_source,
    list_sources,
    registry_stats,
    seed_catalog,
)

from grantbot.funding.schema import (
    initialize_funding_schema,
)

from grantbot.funding.service import (
    funding_intelligence_summary,
)


def pretty(value):
    print(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )
    )


def parser():
    p = argparse.ArgumentParser(
        prog="grantbot-funding",
        description=(
            "GrantBot Pro universal funding "
            "and investor intelligence"
        ),
    )

    sub = p.add_subparsers(
        dest="command"
    )

    sub.add_parser(
        "seed",
        help="Seed universal funding registry.",
    )

    sub.add_parser(
        "sources",
        help="List funding sources.",
    )

    sub.add_parser(
        "stats",
        help="Show registry statistics.",
    )

    sub.add_parser(
        "summary",
        help="Show funding intelligence summary.",
    )

    show = sub.add_parser(
        "show",
        help="Show one funding source.",
    )

    show.add_argument(
        "source_key"
    )

    plan = sub.add_parser(
        "plan",
        help="Generate a discovery plan.",
    )

    plan.add_argument(
        "--state",
        default="Florida",
    )

    plan.add_argument(
        "--county",
        action="append",
        default=[],
    )

    plan.add_argument(
        "--city",
        action="append",
        default=[],
    )

    plan.add_argument(
        "--lane",
        action="append",
        default=[],
    )

    plan.add_argument(
        "--save",
        action="store_true",
    )

    return p


def main():
    initialize_database()
    initialize_funding_schema()

    p = parser()
    args = p.parse_args()

    if args.command == "seed":

        count = seed_catalog()

        print(
            f"Seeded {count} "
            f"universal funding sources."
        )

        return

    if args.command == "sources":

        pretty(
            list_sources()
        )

        return

    if args.command == "stats":

        pretty(
            registry_stats()
        )

        return

    if args.command == "summary":

        pretty(
            funding_intelligence_summary()
        )

        return

    if args.command == "show":

        source = get_source(
            args.source_key
        )

        if not source:
            raise SystemExit(
                "Funding source not found."
            )

        pretty(
            source
        )

        return

    if args.command == "plan":

        plan = build_discovery_plan(
            state=args.state,
            counties=args.county,
            cities=args.city,
            lanes=args.lane or None,
        )

        if args.save:
            saved = save_plan(
                plan
            )

            print(
                f"Saved {saved} "
                f"discovery queries."
            )

        pretty({
            "query_count":
                len(plan),

            "plan":
                plan,
        })

        return

    p.print_help()


if __name__ == "__main__":
    main()
PY

# ==============================================================
# TEST SUITE
# ==============================================================

cat > "$ROOT/tests/test_funding.py" <<'PY'
from grantbot.core.database import (
    initialize_database,
)

from grantbot.funding.planner import (
    build_discovery_plan,
)

from grantbot.funding.precheck import (
    precheck_source,
)

from grantbot.funding.registry import (
    get_source,
    list_sources,
    registry_stats,
    seed_catalog,
)

from grantbot.funding.schema import (
    initialize_funding_schema,
)

from grantbot.investors.structure_guard import (
    analyze_source_structure,
)


def setup_module():
    initialize_database()
    initialize_funding_schema()
    seed_catalog()


def test_registry_has_broad_sources():
    sources = list_sources()

    assert len(
        sources
    ) >= 15


def test_federal_source_exists():
    source = get_source(
        "federal_grants_gov"
    )

    assert source is not None

    assert (
        source[
            "jurisdiction_level"
        ]
        == "FEDERAL"
    )


def test_county_source_exists():
    source = get_source(
        "florida_counties"
    )

    assert source is not None

    assert (
        source[
            "jurisdiction_level"
        ]
        == "COUNTY"
    )


def test_city_source_exists():
    source = get_source(
        "florida_cities"
    )

    assert source is not None

    assert (
        source[
            "jurisdiction_level"
        ]
        == "CITY"
    )


def test_angel_source_guard():
    source = get_source(
        "angel_investors"
    )

    result = (
        analyze_source_structure(
            source
        )
    )

    assert (
        result[
            "requires_investable_entity"
        ]
        is True
    )

    assert (
        result[
            "requires_legal_review"
        ]
        is True
    )


def test_nonprofit_precheck():
    source = get_source(
        "community_foundations"
    )

    result = precheck_source(
        source
    )

    assert (
        result[
            "direct_fit"
        ]
        is True
    )

    assert (
        result[
            "score"
        ]
        == 100
    )


def test_discovery_plan():
    plan = build_discovery_plan(
        state="Florida",
        counties=[
            "Sarasota"
        ],
        cities=[
            "Venice"
        ],
        max_terms_per_lane=1,
    )

    assert len(plan) > 20

    queries = [
        row["query"].lower()
        for row in plan
    ]

    assert any(
        "sarasota county"
        in query
        for query in queries
    )

    assert any(
        "venice"
        in query
        for query in queries
    )


def test_registry_stats():
    stats = registry_stats()

    assert (
        stats[
            "total_sources"
        ]
        >= 15
    )

    assert (
        "FEDERAL"
        in stats[
            "by_jurisdiction"
        ]
    )

    assert (
        "COUNTY"
        in stats[
            "by_jurisdiction"
        ]
    )

    assert (
        "CITY"
        in stats[
            "by_jurisdiction"
        ]
    )
PY

# ==============================================================
# COMPILE
# ==============================================================

cd "$ROOT"

echo
echo "=== Compiling Module 03 ==="

"$PYTHON" \
    -m compileall \
    -q \
    grantbot/funding \
    grantbot/investors \
    tests/test_funding.py

# ==============================================================
# INITIALIZE DATABASE
# ==============================================================

echo
echo "=== Initializing funding intelligence database ==="

PYTHONPATH="$ROOT" \
"$PYTHON" - <<'PY'
from grantbot.core.database import initialize_database
from grantbot.funding.schema import initialize_funding_schema
from grantbot.funding.registry import seed_catalog

initialize_database()
initialize_funding_schema()

count = seed_catalog()

print(
    f"Universal funding registry ready: "
    f"{count} source families."
)
PY

# ==============================================================
# TESTS
# ==============================================================

echo
echo "=== Running Module 03 tests ==="

PYTHONPATH="$ROOT" \
"$PYTHON" \
    -m pytest \
    tests/test_funding.py \
    -q

# ==============================================================
# DISPLAY STATS
# ==============================================================

echo
echo "=== Funding registry statistics ==="

PYTHONPATH="$ROOT" \
"$PYTHON" \
    -m grantbot.funding.cli \
    stats

# ==============================================================
# SAMPLE DISCOVERY PLAN
# ==============================================================

echo
echo "=== Building Florida discovery plan ==="

PYTHONPATH="$ROOT" \
"$PYTHON" \
    -m grantbot.funding.cli \
    plan \
    --state Florida \
    --save \
    >/tmp/grantbot_module03_plan.txt

echo "Discovery plan created and saved."

echo
echo "=============================================================="
echo " MODULE 03 INSTALLED SUCCESSFULLY"
echo "=============================================================="
echo
echo "Funding intelligence now recognizes:"
echo
echo "  Federal"
echo "  Florida state"
echo "  County"
echo "  City / municipal"
echo "  Community redevelopment"
echo "  Continuum of Care / homelessness"
echo "  Community foundations"
echo "  Private foundations"
echo "  Family foundations"
echo "  Corporate giving"
echo "  Bank CRA funding"
echo "  CDFIs"
echo "  Faith-based funding"
echo "  Church partnerships"
echo "  Sponsorships"
echo "  In-kind contributions"
echo "  Angel investors"
echo "  Impact investors"
echo "  Program-related investments"
echo "  Recoverable grants"
echo "  Low-interest financing"
echo "  Capital / construction"
echo "  Land / property"
echo "  Equipment"
echo "  Workforce"
echo "  Reentry"
echo "  Housing"
echo "  Homelessness"
echo "  Community development"
echo "  Economic development"
echo
echo "Useful commands:"
echo
echo "cd ~/grantbot_pro"
echo
echo ".venv/bin/python -m grantbot.funding.cli stats"
echo
echo ".venv/bin/python -m grantbot.funding.cli sources"
echo
echo ".venv/bin/python -m grantbot.funding.cli show angel_investors"
echo
echo ".venv/bin/python -m grantbot.funding.cli plan --state Florida --county Sarasota --city Venice --save"
echo
echo "NEXT:"
echo
echo "MODULE 04 — LIVE FUNDING DISCOVERY ENGINE"
echo
echo "That is where we connect the registry to actual"
echo "federal, state, county, city, foundation and"
echo "investor searches and normalize every result."
echo
