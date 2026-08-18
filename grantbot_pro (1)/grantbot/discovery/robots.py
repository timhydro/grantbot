from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from grantbot.core.logging_config import (
    get_logger,
)


logger = get_logger(
    "discovery.robots"
)


_CACHE: dict[str, RobotFileParser | None] = {}


def can_fetch(
    url: str,
    client,
    user_agent: str,
) -> bool:

    parsed = urlparse(
        url
    )

    root = (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
    )

    if root in _CACHE:
        parser = _CACHE[
            root
        ]

        if parser is None:
            return True

        return parser.can_fetch(
            user_agent,
            url,
        )

    robots_url = (
        root
        + "/robots.txt"
    )

    try:
        text = client.get_text(
            robots_url,
            cache_seconds=3600,
        )

        parser = RobotFileParser()

        parser.set_url(
            robots_url
        )

        parser.parse(
            text.splitlines()
        )

        _CACHE[root] = (
            parser
        )

        return parser.can_fetch(
            user_agent,
            url,
        )

    except Exception as exc:

        logger.debug(
            "robots.txt unavailable for %s: %s",
            root,
            exc,
        )

        _CACHE[root] = None

        return True
