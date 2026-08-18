from __future__ import annotations

import hashlib

from grantbot.core.database import (
    connection,
    utc_now,
)

from grantbot.core.utils import (
    normalize_text,
)


def fingerprint(
    *,
    source_key: str,
    title: str,
    source_url: str | None = None,
    external_id: str | None = None,
    deadline: str | None = None,
) -> str:

    if external_id:
        material = (
            f"{source_key}|"
            f"{external_id}"
        )

    else:
        material = "|".join([
            source_key,
            normalize_text(
                title
            ).lower(),
            normalize_text(
                source_url
            ).lower(),
            normalize_text(
                deadline
            ).lower(),
        ])

    return hashlib.sha256(
        material.encode(
            "utf-8"
        )
    ).hexdigest()


def fingerprint_exists(
    value: str,
) -> bool:

    with connection() as conn:

        row = conn.execute(
            """
            SELECT opportunity_id
            FROM opportunity_fingerprints
            WHERE fingerprint=?
            """,
            (value,),
        ).fetchone()

    return bool(
        row
    )


def store_fingerprint(
    opportunity_id: int,
    value: str,
) -> None:

    with connection() as conn:

        conn.execute(
            """
            INSERT OR IGNORE
            INTO opportunity_fingerprints(
                opportunity_id,
                fingerprint,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                opportunity_id,
                value,
                utc_now(),
            ),
        )
