#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${HOME}/grantbot_pro"

echo "===================================================="
echo " GrantBot Pro - Module 02"
echo " KNOWLEDGE + ORGANIZATIONAL FACT INTELLIGENCE"
echo "===================================================="

if [ ! -f "$ROOT/grantbot/core/database.py" ]; then
    echo "ERROR: Module 01 must be installed first."
    exit 1
fi

mkdir -p \
  "$ROOT/grantbot/knowledge" \
  "$ROOT/data/knowledge" \
  "$ROOT/exports"

touch "$ROOT/grantbot/knowledge/__init__.py"

# ============================================================
# KNOWLEDGE MODELS
# ============================================================

cat > "$ROOT/grantbot/knowledge/models.py" <<'PY'
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FactStatus(str, Enum):
    APPROVED = "APPROVED"
    VERIFIED = "VERIFIED"
    DRAFT = "DRAFT"
    MISSING = "MISSING"


TRUST_ORDER = {
    FactStatus.MISSING.value: 0,
    FactStatus.DRAFT.value: 1,
    FactStatus.VERIFIED.value: 2,
    FactStatus.APPROVED.value: 3,
}


@dataclass
class Fact:
    category: str
    fact_key: str
    value: Optional[str] = None
    status: str = FactStatus.MISSING.value
    source: Optional[str] = None
    confidence: float = 1.0
    notes: Optional[str] = None

    @property
    def usable(self) -> bool:
        return bool(
            self.value
            and self.status
            in {
                FactStatus.APPROVED.value,
                FactStatus.VERIFIED.value,
                FactStatus.DRAFT.value,
            }
        )

    @property
    def grant_safe(self) -> bool:
        return bool(
            self.value
            and self.status
            in {
                FactStatus.APPROVED.value,
                FactStatus.VERIFIED.value,
            }
        )
PY


# ============================================================
# VALIDATION + CONTRADICTION RULES
# ============================================================

cat > "$ROOT/grantbot/knowledge/validators.py" <<'PY'
from __future__ import annotations

import json
import re
from typing import Any

from grantbot.core.errors import ValidationError


VALID_STATUSES = {
    "APPROVED",
    "VERIFIED",
    "DRAFT",
    "MISSING",
}


SENSITIVE_NUMERIC_KEYS = {
    "annual_budget",
    "current_people_served",
    "annual_people_served",
    "people_housed",
    "people_employed",
    "employment_retention",
    "housing_retention",
    "number_of_jobs",
    "starting_wages",
    "current_tiny_homes",
    "planned_tiny_homes",
    "construction_cost",
    "grant_funding_received",
}


def validate_status(status: str) -> str:
    status = str(status).strip().upper()

    if status not in VALID_STATUSES:
        raise ValidationError(
            f"Invalid fact status: {status}"
        )

    return status


def validate_confidence(value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "Confidence must be numeric."
        ) from exc

    if not 0 <= value <= 1:
        raise ValidationError(
            "Confidence must be between 0 and 1."
        )

    return value


def normalize_value(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(
        value,
        (dict, list, tuple, set),
    ):
        if isinstance(value, set):
            value = sorted(value)

        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
        )

    text = str(value).strip()

    if not text:
        return None

    return re.sub(
        r"\s+",
        " ",
        text,
    )


def validate_fact(
    fact_key: str,
    value: Any,
    status: str,
    source: str | None,
) -> None:

    status = validate_status(status)

    normalized = normalize_value(value)

    if status == "MISSING":
        return

    if normalized is None:
        raise ValidationError(
            f"{fact_key}: non-MISSING fact requires a value."
        )

    if status in {"APPROVED", "VERIFIED"}:
        if not source or not str(source).strip():
            raise ValidationError(
                f"{fact_key}: {status} facts require a source."
            )


def requires_numeric_verification(
    fact_key: str,
) -> bool:
    return fact_key in SENSITIVE_NUMERIC_KEYS


def looks_like_numeric_claim(
    value: str | None,
) -> bool:

    if not value:
        return False

    return bool(
        re.search(
            r"\b\d+(?:\.\d+)?(?:%|\b)",
            value,
        )
    )
PY


# ============================================================
# FACT REPOSITORY
# ============================================================

cat > "$ROOT/grantbot/knowledge/repository.py" <<'PY'
from __future__ import annotations

import json
from typing import Any

from grantbot.core.database import (
    audit,
    execute,
    fetch_all,
    fetch_one,
    utc_now,
)
from grantbot.core.errors import ValidationError
from grantbot.knowledge.validators import (
    normalize_value,
    validate_confidence,
    validate_fact,
)


def get_fact(
    fact_key: str,
) -> dict[str, Any] | None:

    return fetch_one(
        """
        SELECT *
        FROM facts
        WHERE fact_key=?
        """,
        (fact_key,),
    )


def list_facts(
    category: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:

    sql = """
        SELECT *
        FROM facts
        WHERE 1=1
    """

    params: list[Any] = []

    if category:
        sql += " AND category=?"
        params.append(category)

    if status:
        sql += " AND status=?"
        params.append(status.upper())

    sql += """
        ORDER BY
            category,
            fact_key
    """

    return fetch_all(
        sql,
        tuple(params),
    )


def save_fact(
    *,
    category: str,
    fact_key: str,
    value: Any = None,
    status: str = "MISSING",
    source: str | None = None,
    confidence: float = 1.0,
    notes: str | None = None,
    allow_downgrade: bool = False,
) -> dict[str, Any]:

    category = str(category).strip().lower()
    fact_key = str(fact_key).strip().lower()

    if not category:
        raise ValidationError(
            "Fact category is required."
        )

    if not fact_key:
        raise ValidationError(
            "Fact key is required."
        )

    status = str(status).strip().upper()

    confidence = validate_confidence(
        confidence
    )

    value = normalize_value(
        value
    )

    validate_fact(
        fact_key,
        value,
        status,
        source,
    )

    existing = get_fact(
        fact_key
    )

    trust = {
        "MISSING": 0,
        "DRAFT": 1,
        "VERIFIED": 2,
        "APPROVED": 3,
    }

    if existing:
        old_status = existing["status"]

        if (
            not allow_downgrade
            and trust.get(status, 0)
            < trust.get(old_status, 0)
        ):
            raise ValidationError(
                f"Refusing to downgrade "
                f"{fact_key} from "
                f"{old_status} to {status}."
            )

        execute(
            """
            UPDATE facts
            SET
                category=?,
                value=?,
                status=?,
                source=?,
                confidence=?,
                notes=?,
                updated_at=?
            WHERE fact_key=?
            """,
            (
                category,
                value,
                status,
                source,
                confidence,
                notes,
                utc_now(),
                fact_key,
            ),
        )

        action = "fact.updated"

    else:
        now = utc_now()

        execute(
            """
            INSERT INTO facts(
                category,
                fact_key,
                value,
                status,
                source,
                confidence,
                notes,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category,
                fact_key,
                value,
                status,
                source,
                confidence,
                notes,
                now,
                now,
            ),
        )

        action = "fact.created"

    result = get_fact(
        fact_key
    )

    audit(
        action=action,
        entity_type="fact",
        entity_id=fact_key,
        details={
            "status": status,
            "category": category,
            "source": source,
        },
    )

    return result


def delete_fact(
    fact_key: str,
) -> bool:

    existing = get_fact(
        fact_key
    )

    if not existing:
        return False

    execute(
        """
        DELETE FROM facts
        WHERE fact_key=?
        """,
        (fact_key,),
    )

    audit(
        action="fact.deleted",
        entity_type="fact",
        entity_id=fact_key,
        details={
            "previous":
                existing,
        },
    )

    return True


def approved_facts():
    return fetch_all(
        """
        SELECT *
        FROM facts
        WHERE status='APPROVED'
          AND value IS NOT NULL
          AND TRIM(value) != ''
        ORDER BY category, fact_key
        """
    )


def verified_facts():
    return fetch_all(
        """
        SELECT *
        FROM facts
        WHERE status IN (
            'APPROVED',
            'VERIFIED'
        )
          AND value IS NOT NULL
          AND TRIM(value) != ''
        ORDER BY category, fact_key
        """
    )


def working_facts():
    return fetch_all(
        """
        SELECT *
        FROM facts
        WHERE status IN (
            'APPROVED',
            'VERIFIED',
            'DRAFT'
        )
          AND value IS NOT NULL
          AND TRIM(value) != ''
        ORDER BY category, fact_key
        """
    )


def missing_facts():
    return fetch_all(
        """
        SELECT *
        FROM facts
        WHERE
            status='MISSING'
            OR value IS NULL
            OR TRIM(value)=''
        ORDER BY category, fact_key
        """
    )


def facts_by_categories(
    categories: list[str],
    *,
    grant_safe_only: bool = False,
) -> list[dict[str, Any]]:

    if not categories:
        return []

    marks = ",".join(
        "?"
        for _ in categories
    )

    sql = f"""
        SELECT *
        FROM facts
        WHERE category IN ({marks})
    """

    params = list(
        categories
    )

    if grant_safe_only:
        sql += """
            AND status IN (
                'APPROVED',
                'VERIFIED'
            )
        """
    else:
        sql += """
            AND status IN (
                'APPROVED',
                'VERIFIED',
                'DRAFT'
            )
        """

    sql += """
        AND value IS NOT NULL
        AND TRIM(value) != ''
        ORDER BY
            CASE status
                WHEN 'APPROVED' THEN 1
                WHEN 'VERIFIED' THEN 2
                WHEN 'DRAFT' THEN 3
                ELSE 4
            END,
            category,
            fact_key
    """

    return fetch_all(
        sql,
        tuple(params),
    )
PY


# ============================================================
# CONTRADICTION ENGINE
# ============================================================

cat > "$ROOT/grantbot/knowledge/contradictions.py" <<'PY'
from __future__ import annotations

from grantbot.knowledge.repository import (
    get_fact,
)


def compare_candidate(
    fact_key: str,
    candidate_value: str,
) -> dict:

    existing = get_fact(
        fact_key
    )

    if not existing:
        return {
            "conflict": False,
            "reason": None,
            "existing": None,
        }

    old = (
        existing.get("value")
        or ""
    ).strip()

    new = (
        candidate_value
        or ""
    ).strip()

    if not old or not new:
        return {
            "conflict": False,
            "reason": None,
            "existing": existing,
        }

    conflict = (
        old.casefold()
        != new.casefold()
    )

    return {
        "conflict": conflict,
        "reason":
            "Candidate value differs "
            "from existing organization fact."
            if conflict
            else None,
        "existing": existing,
    }


def contradiction_report(
    candidates: dict[str, str],
) -> list[dict]:

    conflicts = []

    for key, value in candidates.items():
        result = compare_candidate(
            key,
            value,
        )

        if result["conflict"]:
            conflicts.append({
                "fact_key": key,
                "candidate": value,
                "existing":
                    result["existing"],
                "reason":
                    result["reason"],
            })

    return conflicts
PY


# ============================================================
# BROKEN GROWTH MASTER SEED
# ============================================================

cat > "$ROOT/grantbot/knowledge/seed_brokengrowth.py" <<'PY'
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
PY


# ============================================================
# 128-QUESTION DUE DILIGENCE BANK
# ============================================================

cat > "$ROOT/grantbot/knowledge/question_bank.py" <<'PY'
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeQuestion:
    category: str
    key: str
    question: str
    priority: int


QUESTION_GROUPS = {
    "legal": [
        ("legal_name", "What is the exact legal name of the organization?"),
        ("ein", "What is the organization's EIN?"),
        ("tax_exempt_status", "What is the organization's current federal tax-exempt status?"),
        ("state_registration_number", "What Florida nonprofit or charitable registration numbers are active?"),
        ("date_incorporated", "What date was the organization incorporated?"),
        ("registered_agent", "Who is the registered agent?"),
        ("good_standing", "Is the organization currently in good standing with all required agencies?"),
        ("legal_documents", "Which incorporation, IRS, and registration documents are available for applications?"),
    ],

    "leadership": [
        ("founder_name", "Who founded BrokenGrowthMinistries?"),
        ("executive_director", "Who currently serves as executive director or chief executive?"),
        ("board_members", "Who currently serves on the board?"),
        ("board_expertise", "What professional expertise does each board member contribute?"),
        ("board_meetings", "How frequently does the board meet?"),
        ("leadership_bios", "Are current leadership biographies available?"),
        ("conflict_policy", "Is a written conflict-of-interest policy adopted?"),
        ("succession_plan", "Is there a leadership succession plan?"),
    ],

    "population": [
        ("current_people_served", "How many people are currently served?"),
        ("annual_people_served", "How many people are served annually?"),
        ("projected_people_served", "How many people will the funded program serve?"),
        ("eligibility_requirements", "What exact participant eligibility rules apply?"),
        ("referral_sources", "How are participants referred to the organization?"),
        ("demographics", "What verified participant demographic data is available?"),
        ("geographic_origin", "From which cities or counties do participants primarily come?"),
        ("priority_population", "Which participant groups receive priority and why?"),
    ],

    "housing": [
        ("current_tiny_homes", "How many housing units currently exist?"),
        ("planned_tiny_homes", "How many housing units are planned?"),
        ("housing_capacity", "What is the total planned resident capacity?"),
        ("property_status", "Is the housing property owned, leased, donated, or still being acquired?"),
        ("construction_cost", "What is the documented cost per housing unit?"),
        ("length_of_stay", "What is the intended resident length of stay?"),
        ("resident_fees", "Will residents pay rent or program fees?"),
        ("housing_outcomes", "How will housing stability be measured?"),
    ],

    "employment": [
        ("jobs_provided", "Which jobs will BrokenGrowthMinistries directly provide?"),
        ("number_of_jobs", "How many jobs are expected to be created?"),
        ("starting_wages", "What are the documented starting wages?"),
        ("training_program", "What job-readiness or occupational training will be provided?"),
        ("certifications", "Which certifications can participants earn?"),
        ("employer_partners", "Which employers have committed to partnership?"),
        ("advancement", "What career advancement opportunities will participants have?"),
        ("employment_retention", "How will employment retention be measured?"),
    ],

    "program": [
        ("program_names", "What are the official program names?"),
        ("program_model", "What is the complete program model?"),
        ("intake_process", "What happens from referral through enrollment?"),
        ("case_management", "How will case management operate?"),
        ("mentorship", "How will mentorship be structured?"),
        ("life_skills", "What life-skills curriculum will be used?"),
        ("service_duration", "How long does each major service last?"),
        ("graduation", "What constitutes successful program completion?"),
    ],

    "finance": [
        ("annual_budget", "What is the current approved annual operating budget?"),
        ("program_budget", "What is the current program budget?"),
        ("revenue_sources", "What verified revenue sources currently support the organization?"),
        ("cash_on_hand", "What unrestricted cash is currently available?"),
        ("matching_funds", "What confirmed matching funds are available?"),
        ("in_kind", "What documented in-kind contributions are available?"),
        ("financial_controls", "What internal financial controls are currently used?"),
        ("financial_statements", "Which financial statements are ready for funders?"),
    ],

    "funding": [
        ("federal", "Which federal grant programs are strategic targets?"),
        ("state", "Which Florida state agencies or funding programs are strategic targets?"),
        ("county", "Which county governments should GrantBot monitor?"),
        ("city", "Which cities and municipal programs should GrantBot monitor?"),
        ("foundation", "Which private or community foundations align with the mission?"),
        ("corporate", "Which corporate giving programs align with the mission?"),
        ("faith", "Which faith-based funders align with the ministry model?"),
        ("capital", "Which capital, construction, land, and equipment funding sources are appropriate?"),
    ],

    "investor": [
        ("amount_sought", "How much investment capital is being sought?"),
        ("structure", "What legal structure would receive investment capital?"),
        ("use_of_funds", "Exactly how would investment capital be used?"),
        ("revenue", "What earned-revenue streams could support repayment or sustainability?"),
        ("return", "What financial or impact return can legitimately be offered?"),
        ("impact_metrics", "Which measurable social-impact outcomes would investors receive reports on?"),
        ("risk", "What material risks should prospective investors understand?"),
        ("repayment", "What repayment, redemption, or exit structure is legally and financially realistic?"),
    ],

    "partnerships": [
        ("government", "Which government agencies currently partner with the organization?"),
        ("corrections", "Which corrections or reentry agencies are potential partners?"),
        ("housing", "Which housing organizations are confirmed partners?"),
        ("employers", "Which employers are confirmed partners?"),
        ("churches", "Which churches or ministries are confirmed partners?"),
        ("health", "Which health or behavioral-health providers are partners?"),
        ("education", "Which colleges or training providers are partners?"),
        ("letters", "Which partners can provide current letters of commitment?"),
    ],

    "outcomes": [
        ("immediate", "Which immediate outcomes will be measured?"),
        ("intermediate", "Which intermediate outcomes will be measured?"),
        ("long_term", "Which long-term outcomes will be measured?"),
        ("baseline", "What baseline data exists?"),
        ("targets", "What numeric targets are supported by evidence?"),
        ("tools", "Which tools will collect outcome data?"),
        ("frequency", "How often will outcomes be reviewed?"),
        ("reporting", "Who is responsible for outcome reporting?"),
    ],

    "evidence": [
        ("people_housed", "How many people have been verifiably housed?"),
        ("people_employed", "How many people have been verifiably employed?"),
        ("retention", "What verified housing and employment retention rates exist?"),
        ("testimonials", "Which participant testimonials have documented consent?"),
        ("letters", "Which current partnership or support letters are available?"),
        ("awards", "Which awards, recognitions, or certifications can be verified?"),
        ("media", "Which media coverage can be documented?"),
        ("research", "Which external research supports the program model?"),
    ],

    "compliance": [
        ("donations", "Is there a written donations and gift-acceptance policy?"),
        ("expenses", "Who may authorize organization expenditures?"),
        ("receipts", "What receipt and documentation rules apply?"),
        ("banking", "What bank-account controls and signer rules apply?"),
        ("records", "Is there a written record-retention policy?"),
        ("whistleblower", "Is there a whistleblower policy?"),
        ("nondiscrimination", "What nondiscrimination policies apply?"),
        ("privacy", "How is participant and donor information protected?"),
    ],

    "grant_readiness": [
        ("sam", "Is SAM.gov registration active and when does it expire?"),
        ("uei", "What is the organization's UEI?"),
        ("grants_gov", "Is Grants.gov access active for authorized organization representatives?"),
        ("state_vendor", "Which state vendor registrations are active?"),
        ("county_vendor", "Which county vendor registrations are active?"),
        ("city_vendor", "Which city vendor registrations are active?"),
        ("audit", "Are audited or reviewed financial statements available?"),
        ("attachments", "Which standard grant attachments are ready for immediate submission?"),
    ],

    "community_need": [
        ("problem", "What exact community problems does the organization address?"),
        ("local_data", "What current local data documents those problems?"),
        ("service_gap", "What documented service gaps remain in the target area?"),
        ("barriers", "What barriers prevent participants from reaching stability?"),
        ("housing_need", "What verified housing need exists in the service area?"),
        ("employment_need", "What verified employment barriers exist for the target population?"),
        ("reentry_need", "What verified reentry challenges exist locally?"),
        ("community_voice", "How has community or participant input shaped the program?"),
    ],

    "sustainability": [
        ("funding_mix", "What long-term funding mix is planned?"),
        ("earned_revenue", "Which earned-revenue strategies are realistic?"),
        ("government", "Which recurring government funding streams could support operations?"),
        ("foundation", "Which renewable foundation relationships can be developed?"),
        ("donors", "What individual donor strategy exists?"),
        ("corporate", "What corporate sponsorship strategy exists?"),
        ("reserve", "What operating reserve target has been established?"),
        ("post_grant", "How will services continue after a grant period ends?"),
    ],

    "risk": [
        ("financial", "What are the primary financial risks?"),
        ("program", "What are the primary program-delivery risks?"),
        ("property", "What property or construction risks exist?"),
        ("staffing", "What staffing risks exist?"),
        ("compliance", "What regulatory risks exist?"),
        ("participant", "What participant safety risks require controls?"),
        ("reputation", "What reputational risks require mitigation?"),
        ("continuity", "What continuity plans exist for major disruptions?"),
    ],
}


def build_question_bank():
    questions = []

    priority_categories = {
        "legal",
        "finance",
        "grant_readiness",
        "compliance",
    }

    for category, rows in QUESTION_GROUPS.items():
        for key, question in rows:
            questions.append(
                KnowledgeQuestion(
                    category=category,
                    key=key,
                    question=question,
                    priority=1
                    if category in priority_categories
                    else 2,
                )
            )

    return questions


QUESTIONS = build_question_bank()


def question_count():
    return len(
        QUESTIONS
    )


def by_category(
    category: str,
):
    return [
        q
        for q in QUESTIONS
        if q.category == category
    ]
PY


# ============================================================
# KNOWLEDGE INTELLIGENCE SERVICE
# ============================================================

cat > "$ROOT/grantbot/knowledge/service.py" <<'PY'
from __future__ import annotations

import json
from collections import Counter

from grantbot.knowledge.question_bank import (
    QUESTIONS,
)
from grantbot.knowledge.repository import (
    approved_facts,
    get_fact,
    missing_facts,
    verified_facts,
    working_facts,
)


CRITICAL_KEYS = {
    "legal_name": 100,
    "ein": 100,
    "tax_exempt_status": 100,
    "annual_budget": 95,
    "sam_registration": 95,
    "uei": 95,
    "grants_gov_registration": 95,
    "financial_controls": 90,
    "current_people_served": 90,
    "annual_people_served": 90,
    "eligibility_requirements": 88,
    "program_names": 85,
    "program_descriptions": 85,
    "current_funding": 85,
    "board_members": 82,
    "mailing_address": 80,
}


def knowledge_summary() -> dict:
    working = working_facts()
    verified = verified_facts()
    approved = approved_facts()
    missing = missing_facts()

    categories = Counter(
        row["category"]
        for row in working
    )

    return {
        "total_working_facts":
            len(working),
        "approved":
            len(approved),
        "verified_or_approved":
            len(verified),
        "missing":
            len(missing),
        "categories":
            dict(categories),
        "question_bank_size":
            len(QUESTIONS),
    }


def readiness_score() -> dict:
    missing = missing_facts()

    missing_keys = {
        row["fact_key"]
        for row in missing
    }

    weighted_total = sum(
        CRITICAL_KEYS.values()
    )

    weighted_missing = sum(
        weight
        for key, weight
        in CRITICAL_KEYS.items()
        if key in missing_keys
    )

    if not weighted_total:
        score = 0
    else:
        score = round(
            100
            * (
                1
                - weighted_missing
                / weighted_total
            ),
            1,
        )

    return {
        "score": max(
            0,
            min(100, score),
        ),
        "critical_missing": [
            {
                "fact_key": key,
                "weight": weight,
            }
            for key, weight
            in sorted(
                CRITICAL_KEYS.items(),
                key=lambda item:
                    item[1],
                reverse=True,
            )
            if key in missing_keys
        ],
    }


def next_questions(
    limit: int = 10,
) -> list[dict]:

    missing = {
        row["fact_key"]
        for row in missing_facts()
    }

    results = []

    for q in QUESTIONS:
        candidate_keys = {
            q.key,
        }

        if candidate_keys & missing:
            results.append({
                "category":
                    q.category,
                "fact_key":
                    q.key,
                "question":
                    q.question,
                "priority":
                    q.priority,
            })

    results.sort(
        key=lambda row: (
            row["priority"],
            -CRITICAL_KEYS.get(
                row["fact_key"],
                0,
            ),
            row["category"],
        )
    )

    return results[:limit]


def grant_safe_profile() -> dict:
    facts = verified_facts()

    return {
        row["fact_key"]: {
            "value":
                row["value"],
            "status":
                row["status"],
            "source":
                row["source"],
            "confidence":
                row["confidence"],
        }
        for row in facts
    }


def investor_profile() -> dict:
    categories = {
        "organization",
        "vision",
        "program",
        "impact",
        "finance",
        "investor",
        "funding",
        "evidence",
        "partnerships",
    }

    rows = [
        row
        for row in working_facts()
        if row["category"]
        in categories
    ]

    return {
        "facts": rows,
        "missing_investor_information": [
            row
            for row in missing_facts()
            if row["category"]
            in {
                "investor",
                "finance",
                "evidence",
            }
        ],
    }
PY


# ============================================================
# KNOWLEDGE EXPORTER
# ============================================================

cat > "$ROOT/grantbot/knowledge/exporter.py" <<'PY'
from __future__ import annotations

import json
from pathlib import Path

from grantbot.core.config import settings
from grantbot.knowledge.repository import (
    list_facts,
)
from grantbot.knowledge.service import (
    grant_safe_profile,
    investor_profile,
    knowledge_summary,
    readiness_score,
)


def export_knowledge(
    destination: str | Path | None = None,
) -> Path:

    if destination is None:
        destination = (
            settings.export_dir
            / "broken_growth_knowledge.json"
        )

    destination = Path(
        destination
    )

    payload = {
        "summary":
            knowledge_summary(),
        "grant_readiness":
            readiness_score(),
        "facts":
            list_facts(),
        "grant_safe_profile":
            grant_safe_profile(),
        "investor_profile":
            investor_profile(),
    }

    destination.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return destination
PY


# ============================================================
# TESTS
# ============================================================

cat > "$ROOT/tests/test_knowledge.py" <<'PY'
import unittest

from grantbot.core.database import (
    initialize_database,
)
from grantbot.knowledge.seed_brokengrowth import (
    seed,
)
from grantbot.knowledge.question_bank import (
    question_count,
)
from grantbot.knowledge.repository import (
    get_fact,
    verified_facts,
    missing_facts,
)
from grantbot.knowledge.service import (
    knowledge_summary,
    readiness_score,
    grant_safe_profile,
)


class KnowledgeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        initialize_database()
        seed()

    def test_question_bank_is_large(self):
        self.assertGreaterEqual(
            question_count(),
            120,
        )

    def test_org_name(self):
        fact = get_fact(
            "organization_name"
        )

        self.assertEqual(
            fact["value"],
            "BrokenGrowthMinistries",
        )

        self.assertEqual(
            fact["status"],
            "APPROVED",
        )

    def test_funding_scope(self):
        fact = get_fact(
            "funding_source_scope"
        )

        self.assertIn(
            "angel investors",
            fact["value"],
        )

        self.assertIn(
            "county grants",
            fact["value"],
        )

        self.assertIn(
            "city and municipal grants",
            fact["value"],
        )

    def test_missing_queue(self):
        rows = missing_facts()

        self.assertGreater(
            len(rows),
            50,
        )

    def test_grant_safe(self):
        profile = grant_safe_profile()

        self.assertIn(
            "organization_name",
            profile,
        )

        self.assertNotIn(
            "employment_model",
            profile,
        )

    def test_readiness_score(self):
        result = readiness_score()

        self.assertIn(
            "score",
            result,
        )

        self.assertGreaterEqual(
            result["score"],
            0,
        )

        self.assertLessEqual(
            result["score"],
            100,
        )

    def test_summary(self):
        summary = knowledge_summary()

        self.assertGreaterEqual(
            summary["question_bank_size"],
            120,
        )


if __name__ == "__main__":
    unittest.main()
PY


# ============================================================
# INSTALL + VALIDATE
# ============================================================

cd "$ROOT"

echo
echo "Compiling knowledge module..."

python3 -m compileall \
  -q \
  grantbot/knowledge

echo
echo "Initializing and seeding knowledge..."

PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" - <<'PY'
from grantbot.core.database import initialize_database
from grantbot.knowledge.seed_brokengrowth import seed
from grantbot.knowledge.service import (
    knowledge_summary,
    readiness_score,
    next_questions,
)
from grantbot.knowledge.exporter import export_knowledge

initialize_database()
seed()

print()
print("KNOWLEDGE SUMMARY")
print(knowledge_summary())

print()
print("GRANT READINESS")
print(readiness_score())

print()
print("NEXT QUESTIONS")
for row in next_questions(10):
    print(
        f"- [{row['category']}] "
        f"{row['question']}"
    )

print()
print(
    "EXPORT:",
    export_knowledge()
)
PY

echo
echo "Running knowledge tests..."

PYTHONPATH="$ROOT" \
python3 -m unittest \
  tests.test_knowledge \
  -v

echo
echo "===================================================="
echo " MODULE 02 COMPLETE"
echo "===================================================="
echo
echo "Capabilities installed:"
echo "  APPROVED / VERIFIED / DRAFT / MISSING"
echo "  Provenance tracking"
echo "  Confidence tracking"
echo "  Audit logging"
echo "  Contradiction detection"
echo "  Grant-safe fact retrieval"
echo "  Investor-ready fact retrieval"
echo "  Missing-information prioritization"
echo "  Grant-readiness scoring"
echo "  128-question due-diligence bank"
echo "  Federal funding scope"
echo "  Florida state funding scope"
echo "  County funding scope"
echo "  City/municipal funding scope"
echo "  Foundation funding scope"
echo "  Corporate funding scope"
echo "  Faith-based funding scope"
echo "  Capital/construction funding scope"
echo "  Angel investor scope"
echo "  Impact investment scope"
echo
echo "NEXT:"
echo " Module 03 - Universal Funding Source Registry"
echo " + City/County/State/Federal/Foundation/Corporate"
echo " + Angel/Impact Investor Intelligence"
echo " + Source connectors and discovery architecture"
