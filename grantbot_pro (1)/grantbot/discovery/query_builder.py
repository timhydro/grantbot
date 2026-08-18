from __future__ import annotations


def build_web_query(
    plan_row: dict,
) -> str:

    base = (
        plan_row.get(
            "query"
        )
        or ""
    ).strip()

    source_kind = (
        plan_row.get(
            "source_kind"
        )
        or ""
    ).upper()

    jurisdiction = (
        plan_row.get(
            "jurisdiction"
        )
        or ""
    ).upper()

    lane = (
        plan_row.get(
            "lane"
        )
        or ""
    ).replace(
        "_",
        " ",
    )

    additions = []

    if source_kind == "GOVERNMENT":
        additions.extend([
            "grant funding",
            "application",
        ])

        if jurisdiction in {
            "FEDERAL",
            "STATE",
            "COUNTY",
            "CITY",
            "MUNICIPAL",
        }:
            additions.append(
                "site:.gov"
            )

    elif source_kind in {
        "FOUNDATION",
        "COMMUNITY_FOUNDATION",
        "FAMILY_FOUNDATION",
    }:
        additions.extend([
            "foundation",
            "grant application",
        ])

    elif source_kind == "CORPORATE":
        additions.extend([
            "corporate giving",
            "community grant",
        ])

    elif source_kind == "BANK":
        additions.extend([
            "community reinvestment",
            "grant",
        ])

    elif source_kind == "CDFI":
        additions.extend([
            "CDFI",
            "community development finance",
        ])

    elif source_kind in {
        "FAITH_BASED",
        "CHURCH",
    }:
        additions.extend([
            "faith based",
            "ministry funding",
        ])

    elif source_kind in {
        "ANGEL_NETWORK",
        "ANGEL_INVESTOR",
    }:
        additions.extend([
            "angel investor",
            "social enterprise",
        ])

    elif source_kind in {
        "IMPACT_INVESTOR",
        "IMPACT_FUND",
        "PHILANTHROPIC_INVESTOR",
    }:
        additions.extend([
            "impact investment",
            "social impact",
        ])

    elif source_kind == "COMMUNITY_REDEVELOPMENT":
        additions.extend([
            "community redevelopment agency",
            "funding",
        ])

    elif source_kind == "CONTINUUM_OF_CARE":
        additions.extend([
            "continuum of care",
            "funding",
        ])

    return " ".join(
        [
            base,
            lane,
            *additions,
        ]
    ).strip()
