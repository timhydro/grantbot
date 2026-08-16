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
