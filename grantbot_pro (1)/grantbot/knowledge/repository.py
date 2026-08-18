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
