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
