# GrantBot Review-and-Submit Queue

This directory is the human-review workspace for funding applications, loans, sponsorships, CDFI inquiries, fiscal-sponsor requests, crowdfunding applications, and impact-investor outreach.

Each opportunity must have its own folder. The folder should contain a prefilled review packet plus explicit human-only items such as credentials, signatures, attestations, financial figures, board approvals, banking information, guarantees, or payment steps.

## Current Packets

- `pensacola_can_fiscal_sponsorship/` — fiscal sponsorship
- `kiva_us/` — crowdfunded microloan
- `publix_housing_shelter/` — corporate housing/shelter grant
- `walmart_spark_good/` — corporate local grant
- `florida_housing_plp/` — affordable-housing predevelopment loan
- `florida_community_loan_fund/` — Florida CDFI financing
- `clearinghouse_cdfi/` — community-development financing
- `impact_angel_investor_outreach/` — impact/angel/PRI/recoverable-capital outreach

## Required Statuses

- `DRAFT` — application content is being assembled
- `NEEDS_USER` — human factual input/credential/financial data is missing
- `READY_FOR_REVIEW` — GrantBot has completed all safe prefill work
- `READY_TO_SUBMIT` — user has confirmed all facts and only final submission remains
- `SUBMITTED` — user/authorized person submitted the application
- `HOLD` — potentially viable but blocked by timing, tax status, structure, or missing prerequisite
- `INELIGIBLE` — verified hard eligibility failure

## Safety / Accuracy Rules

1. Never invent EIN, UEI, tax-exempt status, revenue, banking data, financial statements, property values, collateral, guarantees, board approvals, signatures, or certifications.
2. A pending 501(c)(3) applicant must never be presented as IRS-approved.
3. If fiscal sponsorship is allowed, route the opportunity to the fiscal-sponsor workflow instead of rejecting it automatically.
4. Angel/equity opportunities must never offer ownership in the charitable nonprofit. Route equity to an appropriately structured social-enterprise entity after legal/tax review.
5. Repayable capital must show repayment and underwriting requirements separately from grants.
6. Every final application remains subject to authorized human review and submission.
