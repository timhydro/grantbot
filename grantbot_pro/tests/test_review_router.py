from grantbot.applications.review_workspace import ReviewStatus
from grantbot.automation.review_router import classify_funding_type, route_for_review
from grantbot.eligibility.tax_status import TaxStatus


def _analysis(*, score=85, requirements="", title="Test Grant", hard_reject=False):
    return {
        "id": "test-1",
        "title": title,
        "funder": "Test Funder",
        "score": score,
        "hard_reject": hard_reject,
        "deadline": None,
        "amount": 5000,
        "source_url": "https://example.org",
        "missing_information": [],
        "nofo": {
            "eligibility": requirements,
            "requirements": requirements,
            "raw_text": requirements,
        },
    }


def test_below_threshold_is_not_created():
    route = route_for_review(_analysis(score=55))
    assert route.should_create is False


def test_pending_501c3_required_goes_to_hold():
    route = route_for_review(
        _analysis(requirements="Applicants must be a 501(c)(3). IRS determination letter required."),
        applicant_status=TaxStatus.PENDING_501C3,
    )
    assert route.should_create is True
    assert route.status == ReviewStatus.HOLD
    assert route.tax_route == "WAIT_FOR_DETERMINATION"


def test_faith_based_route_is_kept_for_review():
    route = route_for_review(
        _analysis(requirements="A church or other faith-based organization may apply."),
        applicant_status=TaxStatus.PENDING_501C3,
    )
    assert route.should_create is True
    assert route.status == ReviewStatus.NEEDS_USER
    assert route.tax_route == "FAITH_BASED_EXCEPTION"


def test_fiscal_sponsor_route_is_kept():
    route = route_for_review(
        _analysis(requirements="Applicants may use a fiscal sponsor."),
        applicant_status=TaxStatus.PENDING_501C3,
        has_fiscal_sponsor=False,
    )
    assert route.should_create is True
    assert route.status == ReviewStatus.NEEDS_USER
    assert route.tax_route == "FISCAL_SPONSOR_NEEDED"


def test_cdfi_classification():
    assert classify_funding_type("Community Development Financial Institution CDFI loan") == "CDFI_LOAN"


def test_angel_classification():
    assert classify_funding_type("Impact investor and angel investor equity opportunity") == "IMPACT_OR_ANGEL_INVESTMENT"
