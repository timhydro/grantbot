from __future__ import annotations


SEARCH_LANES = {
    "reentry": [
        "reentry", "returning citizens", "justice involved", "post incarceration", "prison reentry", "jail reentry", "second chance",
    ],
    "housing": [
        "affordable housing", "supportive housing", "tiny homes", "housing stability", "transitional housing", "permanent housing", "housing development",
    ],
    "homelessness": [
        "homelessness", "homeless services", "rapid rehousing", "housing first", "unsheltered homelessness", "continuum of care",
    ],
    "workforce": [
        "workforce development", "job training", "employment services", "occupational training", "career pathways", "returning citizen employment",
    ],
    "community_development": [
        "community development", "neighborhood revitalization", "community revitalization", "economic opportunity", "low income communities",
    ],
    "capital": [
        "capital grant", "construction grant", "property acquisition", "land acquisition", "facility development", "equipment grant",
    ],
    "economic_development": [
        "economic development", "social enterprise", "job creation", "economic mobility", "community wealth",
    ],
    "foundation": [
        "foundation grant", "community foundation", "family foundation", "general operating support", "capacity building",
    ],
    "faith": [
        "faith based grant", "ministry grant", "church foundation", "Christian foundation", "community ministry funding",
    ],
    "corporate": [
        "corporate giving", "corporate foundation", "community investment", "corporate sponsorship", "in kind donation",
    ],
    "bank_cra": [
        "community reinvestment", "CRA grant", "bank foundation", "community development finance", "low income community investment",
    ],
    "investor": [
        "impact investor", "angel investor", "social impact investment", "program related investment", "recoverable grant", "mission investment",
    ],
    "cdfi": [
        "CDFI loan", "community development loan", "nonprofit facility loan", "supportive housing loan", "mission lender", "community facility financing",
    ],
    "microloan": [
        "zero interest microloan", "crowdfunded loan", "nonprofit microloan", "social enterprise microloan", "small business microloan",
    ],
    "fiscal_sponsor": [
        "fiscal sponsor", "fiscal sponsorship application", "fiscal sponsor nonprofit startup", "fiscal sponsor community project",
    ],
    "crowdfunding": [
        "community crowdfunding", "investment crowdfunding", "crowdfunded business loan", "local investment crowdfunding", "donation crowdfunding",
    ],
    "pri": [
        "program related investment", "PRI foundation", "recoverable grant", "mission related investment", "low interest charitable loan",
    ],
    "angel_social_enterprise": [
        "social enterprise angel investor", "impact angel network", "Florida angel investor social enterprise", "mission driven startup investor",
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
    "cdfi",
    "microloan",
    "fiscal_sponsor",
    "crowdfunding",
    "pri",
    "investor",
    "angel_social_enterprise",
]
