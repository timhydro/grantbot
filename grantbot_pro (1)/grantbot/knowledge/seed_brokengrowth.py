from __future__ import annotations

import json

from grantbot.knowledge.repository import (
    save_fact,
)


APPROVED = [
    {
        "category": "organization",
        "fact_key": "organization_name",
        "value": "BrokenGrowthMinistries",
        "source": "Founder",
    },

    {
        "category": "geography",
        "fact_key": "primary_geographic_focus",
        "value": "Florida",
        "source": "Founder",
    },

    {
        "category": "vision",
        "fact_key": "vision_statement",
        "value":
            "BrokenGrowthMinistries envisions a Florida "
            "where incarceration and homelessness do not "
            "define a person's future, where every "
            "individual has access to a safe place to live, "
            "meaningful work, supportive community, and "
            "the opportunity to discover their God-given "
            "purpose.",
        "source": "Founder",
    },

    {
        "category": "population",
        "fact_key": "primary_populations",
        "value":
            "Individuals recently released from prison "
            "or jail and people experiencing homelessness.",
        "source": "Founder",
    },

    {
        "category": "funding",
        "fact_key": "funding_source_scope",
        "value": json.dumps([
            "federal grants",
            "state grants",
            "county grants",
            "city and municipal grants",
            "community redevelopment agency funding",
            "housing grants",
            "homelessness grants",
            "reentry grants",
            "justice-related grants",
            "workforce grants",
            "job training grants",
            "community development grants",
            "economic development grants",
            "capital grants",
            "construction grants",
            "land and property funding",
            "equipment grants",
            "operating grants",
            "general operating support",
            "program grants",
            "foundation grants",
            "family foundation grants",
            "community foundation grants",
            "corporate philanthropy",
            "corporate grants",
            "bank community reinvestment funding",
            "faith-based funding",
            "church and ministry funding",
            "matching grants",
            "challenge grants",
            "in-kind opportunities",
            "sponsorships",
            "program-related investments",
            "impact investments",
            "angel investors",
            "philanthropic investors",
            "social impact capital",
            "recoverable grants",
            "forgivable financing",
            "low-interest mission financing"
        ]),
        "source": "Founder directive",
    },
]


DRAFT = [
    {
        "category": "program",
        "fact_key": "program_model",
        "value":
            "The planned model integrates housing, "
            "employment, workforce development, life "
            "skills, mentorship, supportive community, "
            "resource navigation, reentry support, "
            "personal development, independence, "
            "and purpose.",
    },

    {
        "category": "housing",
        "fact_key": "tiny_home_model",
        "value":
            "Tiny-home housing is planned as part of "
            "a broader restoration and reentry model.",
    },

    {
        "category": "employment",
        "fact_key": "employment_model",
        "value":
            "Employment opportunity, workforce development, "
            "and meaningful work are planned as core "
            "components of the organization model.",
    },

    {
        "category": "impact",
        "fact_key": "conceptual_pathway",
        "value":
            "Safe housing to stability to employment to "
            "supportive community to independence to purpose.",
    },
]


MISSING = {
    "legal": [
        "legal_name",
        "ein",
        "tax_exempt_status",
        "tax_exempt_determination_date",
        "state_registration_number",
        "date_incorporated",
        "date_founded",
        "registered_agent",
    ],

    "leadership": [
        "founder_name",
        "executive_director",
        "board_chair",
        "board_members",
        "board_size",
        "leadership_bios",
        "conflict_of_interest_policy",
        "succession_plan",
    ],

    "location": [
        "mailing_address",
        "physical_address",
        "service_area",
        "counties_served",
        "cities_served",
        "rural_urban_classification",
        "property_location",
        "property_ownership_status",
    ],

    "population": [
        "current_people_served",
        "annual_people_served",
        "projected_people_served",
        "age_range",
        "gender_demographics",
        "race_ethnicity_demographics",
        "income_demographics",
        "eligibility_requirements",
    ],

    "housing": [
        "current_tiny_homes",
        "planned_tiny_homes",
        "housing_capacity",
        "resident_length_of_stay",
        "resident_fees",
        "utilities_model",
        "construction_cost",
        "development_timeline",
    ],

    "employment": [
        "jobs_provided",
        "number_of_jobs",
        "starting_wages",
        "full_time_positions",
        "part_time_positions",
        "training_program",
        "certifications",
        "employer_partners",
    ],

    "program": [
        "program_names",
        "program_descriptions",
        "program_staff",
        "program_capacity",
        "intake_process",
        "case_management_model",
        "mentorship_structure",
        "life_skills_curriculum",
    ],

    "transportation": [
        "transportation_services",
        "vehicles_available",
        "transit_partners",
        "transportation_budget",
        "participant_transportation_plan",
        "employment_transportation",
        "medical_transportation",
        "license_restoration_support",
    ],

    "finance": [
        "annual_budget",
        "operating_expenses",
        "program_expenses",
        "administrative_expenses",
        "current_funding",
        "grant_funding_received",
        "donation_revenue",
        "earned_revenue",
    ],

    "fundraising": [
        "fundraising_goal",
        "grant_pipeline_value",
        "individual_donor_count",
        "major_donors",
        "monthly_donor_program",
        "corporate_sponsors",
        "foundation_relationships",
        "capital_campaign_status",
    ],

    "investor": [
        "investment_amount_sought",
        "investor_use_of_funds",
        "investor_structure",
        "repayment_model",
        "revenue_model",
        "impact_investment_structure",
        "investor_return_model",
        "investor_exit_or_repayment_plan",
    ],

    "partnerships": [
        "government_partners",
        "city_partners",
        "county_partners",
        "state_partners",
        "church_partners",
        "employer_partners_confirmed",
        "housing_partners",
        "service_provider_partners",
    ],

    "evidence": [
        "people_housed",
        "people_employed",
        "employment_retention",
        "housing_retention",
        "successful_reentries",
        "participant_testimonials",
        "partner_letters",
        "community_impact_data",
    ],

    "compliance": [
        "financial_controls",
        "donation_policy",
        "expense_approval_policy",
        "record_retention_policy",
        "whistleblower_policy",
        "nondiscrimination_policy",
        "privacy_policy",
        "background_check_policy",
    ],

    "outcomes": [
        "primary_outcomes",
        "outcome_targets",
        "measurement_tools",
        "data_collection_process",
        "evaluation_frequency",
        "baseline_data",
        "long_term_tracking",
        "evaluation_partner",
    ],

    "grant_readiness": [
        "sam_registration",
        "uei",
        "grants_gov_registration",
        "state_vendor_registration",
        "county_vendor_registrations",
        "city_vendor_registrations",
        "w9_available",
        "audited_financials",
    ],
}


def seed():
    for row in APPROVED:
        save_fact(
            category=row["category"],
            fact_key=row["fact_key"],
            value=row["value"],
            status="APPROVED",
            source=row["source"],
            confidence=1.0,
        )

    for row in DRAFT:
        save_fact(
            category=row["category"],
            fact_key=row["fact_key"],
            value=row["value"],
            status="DRAFT",
            source="Program planning",
            confidence=0.65,
        )

    for category, keys in MISSING.items():
        for key in keys:
            try:
                save_fact(
                    category=category,
                    fact_key=key,
                    value=None,
                    status="MISSING",
                    source=None,
                    confidence=0.0,
                )
            except Exception:
                # Existing higher-trust facts remain untouched.
                pass


if __name__ == "__main__":
    seed()
    print("BrokenGrowthMinistries knowledge seed complete.")
