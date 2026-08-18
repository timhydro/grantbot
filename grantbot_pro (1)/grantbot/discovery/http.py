from __future__ import annotations

import json
import os
import time

from dataclasses import dataclass
from typing import Any

import requests

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from grantbot.core.errors import (
    ExternalServiceError,
)

from grantbot.core.logging_config import (
    get_logger,
)

from grantbot.discovery.cache import (
    FileCache,
)


logger = get_logger(
    "discovery.http"
)


@dataclass
class HttpResponse:
    url: str
    status_code: int
    headers: dict
    text: str
    from_cache: bool = False

    def json(self):
        return json.loads(
            self.text
        )


class HttpClient:

    def __init__(
        self,
        *,
        timeout: int | None = None,
        cache_seconds: int | None = None,
        delay: float | None = None,
        max_response_mb: int | None = None,
        user_agent: str | None = None,
    ):

        self.timeout = (
            timeout
            if timeout is not None
            else int(
                os.getenv(
                    "GRANTBOT_HTTP_TIMEOUT",
                    "30",
                )
            )
        )

        self.cache_seconds = (
            cache_seconds
            if cache_seconds is not None
            else int(
                os.getenv(
                    "GRANTBOT_HTTP_CACHE_SECONDS",
                    "900",
                )
            )
        )

        self.delay = (
            delay
            if delay is not None
            else float(
                os.getenv(
                    "GRANTBOT_DISCOVERY_DELAY",
                    "0.35",
                )
            )
        )

        self.max_response_bytes = (
            max_response_mb
            if max_response_mb is not None
            else int(
                os.getenv(
                    "GRANTBOT_MAX_RESPONSE_MB",
                    "15",
                )
            )
        ) * 1024 * 1024

        self.user_agent = (
            user_agent
            or (
                "GrantBotPro/4.0 "
                "(nonprofit-funding-research)"
            )
        )

        retries = int(
            os.getenv(
                "GRANTBOT_HTTP_RETRIES",
                "3",
            )
        )

        backoff = float(
            os.getenv(
                "GRANTBOT_HTTP_BACKOFF",
                "0.8",
            )
        )

        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=backoff,
            status_forcelist=(
                429,
                500,
                502,
                503,
                504,
            ),
            allowed_methods=frozenset({
                "GET",
                "POST",
                "HEAD",
            }),
            respect_retry_after_header=True,
            raise_on_status=False,
        )

        self.session = (
            requests.Session()
        )

        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=10,
            pool_maxsize=10,
        )

        self.session.mount(
            "https://",
            adapter,
        )

        self.session.mount(
            "http://",
            adapter,
        )

        self.cache = FileCache()

        self._last_request = 0.0

    def _throttle(self):

        elapsed = (
            time.monotonic()
            - self._last_request
        )

        remaining = (
            self.delay
            - elapsed
        )

        if remaining > 0:
            time.sleep(
                remaining
            )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        json_body: Any = None,
        data: Any = None,
        use_cache: bool = True,
        cache_seconds: int | None = None,
    ) -> HttpResponse:

        method = method.upper()

        cache_payload = {
            "params":
                params,

            "json":
                json_body,

            "data":
                data,
        }

        cache_key = (
            self.cache.key_for(
                method,
                url,
                cache_payload,
            )
        )

        ttl = (
            self.cache_seconds
            if cache_seconds is None
            else cache_seconds
        )

        if use_cache:
            cached = self.cache.get(
                cache_key,
                ttl,
            )

            if cached:
                return HttpResponse(
                    url=cached[
                        "url"
                    ],
                    status_code=cached[
                        "status_code"
                    ],
                    headers=cached[
                        "headers"
                    ],
                    text=cached[
                        "text"
                    ],
                    from_cache=True,
                )

        final_headers = {
            "User-Agent":
                self.user_agent,

            "Accept":
                "*/*",
        }

        if headers:
            final_headers.update(
                headers
            )

        self._throttle()

        try:
            response = (
                self.session.request(
                    method,
                    url,
                    headers=final_headers,
                    params=params,
                    json=json_body,
                    data=data,
                    timeout=self.timeout,
                )
            )

            self._last_request = (
                time.monotonic()
            )

        except requests.RequestException as exc:
            raise ExternalServiceError(
                f"{method} {url} failed: {exc}"
            ) from exc

        length_header = (
            response.headers.get(
                "Content-Length"
            )
        )

        if length_header:
            try:
                if int(
                    length_header
                ) > self.max_response_bytes:
                    raise ExternalServiceError(
                        "Response exceeds configured "
                        f"size limit: {url}"
                    )

            except ValueError:
                pass

        raw = response.content

        if (
            len(raw)
            > self.max_response_bytes
        ):
            raise ExternalServiceError(
                "Response exceeded configured "
                f"size limit: {url}"
            )

        text = response.text

        result = HttpResponse(
            url=str(
                response.url
            ),
            status_code=int(
                response.status_code
            ),
            headers=dict(
                response.headers
            ),
            text=text,
        )

        if (
            response.status_code
            >= 400
        ):
            raise ExternalServiceError(
                f"{method} {url} returned "
                f"HTTP {response.status_code}"
            )

        if use_cache:
            self.cache.set(
                cache_key,
                {
                    "url":
                        result.url,

                    "status_code":
                        result.status_code,

                    "headers":
                        result.headers,

                    "text":
                        result.text,
                },
            )

        return result

    def get_text(
        self,
        url: str,
        **kwargs,
    ) -> str:

        return self.request(
            "GET",
            url,
            **kwargs,
        ).text

    def get_json(
        self,
        url: str,
        **kwargs,
    ):

        response = self.request(
            "GET",
            url,
            **kwargs,
        )

        try:
            return response.json()

        except json.JSONDecodeError as exc:
            raise ExternalServiceError(
                f"Invalid JSON received from {url}"
            ) from exc

    def post_json(
        self,
        url: str,
        *,
        json_body,
        **kwargs,
    ):

        response = self.request(
            "POST",
            url,
            headers={
                "Content-Type":
                    "application/json",
            },
            json_body=json_body,
            **kwargs,
        )

        try:
            return response.json()

        except json.JSONDecodeError as exc:
            raise ExternalServiceError(
                f"Invalid JSON received from {url}"
            ) from exc
