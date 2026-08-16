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
