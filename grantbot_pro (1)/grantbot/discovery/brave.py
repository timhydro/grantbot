from __future__ import annotations

import os

from urllib.parse import (
    urlparse,
)

from grantbot.core.errors import (
    ExternalServiceError,
)

from grantbot.discovery.http import (
    HttpClient,
)


BRAVE_URL = (
    "https://api.search.brave.com/"
    "res/v1/web/search"
)


class BraveSearchProvider:

    def __init__(
        self,
        api_key: str | None = None,
        client: HttpClient | None = None,
    ):

        self.api_key = (
            api_key
            or os.getenv(
                "BRAVE_SEARCH_API_KEY",
                "",
            )
        ).strip()

        self.client = (
            client
            or HttpClient()
        )

    @property
    def enabled(self) -> bool:

        configured = (
            os.getenv(
                "GRANTBOT_BRAVE_ENABLED",
                "0",
            )
            .strip()
            .lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
        )

        return bool(
            configured
            and self.api_key
        )

    def search(
        self,
        query: str,
        *,
        count: int = 10,
    ) -> list[dict]:

        if not self.enabled:
            raise ExternalServiceError(
                "Brave Search is not configured. "
                "Set GRANTBOT_BRAVE_ENABLED=1 "
                "and BRAVE_SEARCH_API_KEY."
            )

        response = (
            self.client.get_json(
                BRAVE_URL,

                headers={
                    "Accept":
                        "application/json",

                    "X-Subscription-Token":
                        self.api_key,
                },

                params={
                    "q":
                        query,

                    "count":
                        min(
                            max(
                                int(
                                    count
                                ),
                                1,
                            ),
                            20,
                        ),

                    "country":
                        "us",

                    "search_lang":
                        "en",
                },

                use_cache=True,
            )
        )

        web = (
            response.get(
                "web"
            )
            or {}
        )

        results = (
            web.get(
                "results"
            )
            or []
        )

        cleaned = []

        for result in results:

            url = (
                result.get(
                    "url"
                )
                or ""
            )

            if not url:
                continue

            parsed = urlparse(
                url
            )

            cleaned.append({
                "title":
                    result.get(
                        "title"
                    )
                    or "",

                "url":
                    url,

                # Used transiently for relevance only.
                # GrantBot does not need to persist it.
                "description":
                    result.get(
                        "description"
                    )
                    or "",

                "domain":
                    parsed.netloc.lower(),
            })

        return cleaned
