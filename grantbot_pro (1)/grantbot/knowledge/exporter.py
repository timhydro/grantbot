from __future__ import annotations

import json
from pathlib import Path

from grantbot.core.config import settings
from grantbot.knowledge.repository import (
    list_facts,
)
from grantbot.knowledge.service import (
    grant_safe_profile,
    investor_profile,
    knowledge_summary,
    readiness_score,
)


def export_knowledge(
    destination: str | Path | None = None,
) -> Path:

    if destination is None:
        destination = (
            settings.export_dir
            / "broken_growth_knowledge.json"
        )

    destination = Path(
        destination
    )

    payload = {
        "summary":
            knowledge_summary(),
        "grant_readiness":
            readiness_score(),
        "facts":
            list_facts(),
        "grant_safe_profile":
            grant_safe_profile(),
        "investor_profile":
            investor_profile(),
    }

    destination.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return destination
