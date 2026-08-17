from __future__ import annotations

from typing import Any


REQUIRED_SECTIONS = (
    "need",
    "inputs",
    "activities",
    "outputs",
    "short_term_outcomes",
    "intermediate_outcomes",
    "long_term_impact",
    "metrics",
)


def validate_logic_model(model: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    issues: list[str] = []
    for section in REQUIRED_SECTIONS:
        value = model.get(section)
        if value in (None, "", [], {}):
            missing.append(section)

    metrics = model.get("metrics")
    if isinstance(metrics, list):
        for index, metric in enumerate(metrics, start=1):
            if not isinstance(metric, dict):
                issues.append(f"metric {index} must be an object")
                continue
            for field in ("name", "target", "timeframe", "measurement_method"):
                if metric.get(field) in (None, ""):
                    issues.append(f"metric {index} missing {field}")
    elif metrics not in (None, ""):
        issues.append("metrics must be a list")

    return {
        "valid": not missing and not issues,
        "missing_sections": missing,
        "issues": issues,
        "required_sections": list(REQUIRED_SECTIONS),
    }
