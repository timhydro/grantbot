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
