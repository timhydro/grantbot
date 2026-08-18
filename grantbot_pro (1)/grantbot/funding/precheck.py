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
