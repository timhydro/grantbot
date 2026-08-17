from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


CENT = Decimal("0.01")


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"Invalid monetary value: {value!r}") from exc
    if amount < 0:
        raise ValueError("Budget values cannot be negative")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_budget(
    *,
    items: list[dict[str, Any]],
    indirect_rate_percent: float = 0.0,
    indirect_base_categories: list[str] | None = None,
    cash_match: float = 0.0,
    in_kind_match: float = 0.0,
    participant_count: int | None = None,
    housing_unit_count: int | None = None,
) -> dict[str, Any]:
    if not items:
        raise ValueError("At least one budget item is required")
    if not 0 <= float(indirect_rate_percent) <= 100:
        raise ValueError("indirect_rate_percent must be between 0 and 100")

    normalized: list[dict[str, Any]] = []
    direct_total = Decimal("0")
    category_totals: dict[str, Decimal] = {}
    for index, item in enumerate(items, start=1):
        category = str(item.get("category", "")).strip().upper()
        description = str(item.get("description", "")).strip()
        if not category or not description:
            raise ValueError(f"Budget item {index} requires category and description")
        quantity = _money(item.get("quantity", 1))
        unit_cost = _money(item.get("unit_cost", 0))
        months = _money(item.get("months", 1))
        amount = (quantity * unit_cost * months).quantize(CENT, rounding=ROUND_HALF_UP)
        direct_total += amount
        category_totals[category] = category_totals.get(category, Decimal("0")) + amount
        normalized.append(
            {
                "category": category,
                "description": description,
                "quantity": float(quantity),
                "unit_cost": float(unit_cost),
                "months": float(months),
                "amount": float(amount),
            }
        )

    base_categories = {str(item).strip().upper() for item in (indirect_base_categories or category_totals)}
    indirect_base = sum(
        (amount for category, amount in category_totals.items() if category in base_categories),
        Decimal("0"),
    )
    indirect = (
        indirect_base * Decimal(str(indirect_rate_percent)) / Decimal("100")
    ).quantize(CENT, rounding=ROUND_HALF_UP)
    cash = _money(cash_match)
    in_kind = _money(in_kind_match)
    grant_request = (direct_total + indirect).quantize(CENT, rounding=ROUND_HALF_UP)
    total_project = (grant_request + cash + in_kind).quantize(CENT, rounding=ROUND_HALF_UP)

    if participant_count is not None and participant_count <= 0:
        raise ValueError("participant_count must be positive")
    if housing_unit_count is not None and housing_unit_count <= 0:
        raise ValueError("housing_unit_count must be positive")

    return {
        "items": normalized,
        "category_totals": {key: float(value.quantize(CENT)) for key, value in category_totals.items()},
        "direct_total": float(direct_total.quantize(CENT)),
        "indirect_base": float(indirect_base.quantize(CENT)),
        "indirect_rate_percent": float(indirect_rate_percent),
        "indirect_amount": float(indirect),
        "grant_request": float(grant_request),
        "cash_match": float(cash),
        "in_kind_match": float(in_kind),
        "total_project_cost": float(total_project),
        "cost_per_participant": (
            float((total_project / participant_count).quantize(CENT))
            if participant_count is not None
            else None
        ),
        "cost_per_housing_unit": (
            float((total_project / housing_unit_count).quantize(CENT))
            if housing_unit_count is not None
            else None
        ),
    }
