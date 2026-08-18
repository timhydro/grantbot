#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${HOME}/grantbot_pro"
PYTHON="${ROOT}/.venv/bin/python"

echo
echo "================================================================"
echo " GRANTBOT PRO"
echo " MODULE 04 — LIVE UNIVERSAL FUNDING DISCOVERY ENGINE"
echo "================================================================"
echo

# ==============================================================
# REQUIRE PRIOR MODULES
# ==============================================================

for REQUIRED in \
    "$ROOT/grantbot/core/database.py" \
    "$ROOT/grantbot/knowledge/repository.py" \
    "$ROOT/grantbot/funding/registry.py" \
    "$ROOT/grantbot/funding/planner.py" \
    "$ROOT/grantbot/funding/ingest.py"
do
    if [ ! -f "$REQUIRED" ]; then
        echo "ERROR: Missing required module:"
        echo "  $REQUIRED"
        echo
        echo "Modules 01, 02, and 03 must be installed first."
        exit 1
    fi
done

if [ ! -x "$PYTHON" ]; then
    echo "ERROR: GrantBot .venv is missing."
    echo
    echo "Run:"
    echo "cd ~/grantbot_pro && bash bootstrap.sh"
    exit 1
fi

mkdir -p \
    "$ROOT/grantbot/discovery" \
    "$ROOT/grantbot/funding/connectors" \
    "$ROOT/data/cache/http" \
    "$ROOT/data/funding/pages" \
    "$ROOT/data/funding/search" \
    "$ROOT/tests"

touch "$ROOT/grantbot/discovery/__init__.py"
touch "$ROOT/grantbot/funding/connectors/__init__.py"

# ==============================================================
# ADD DISCOVERY SETTINGS
# ==============================================================

if ! grep -q '^GRANTBOT_HTTP_CACHE_SECONDS=' "$ROOT/.env.example" 2>/dev/null; then
cat >> "$ROOT/.env.example" <<'ENV'

# --------------------------------------------------------------
# Module 04 - Live Discovery
# --------------------------------------------------------------

GRANTBOT_HTTP_CACHE_SECONDS=900
GRANTBOT_HTTP_TIMEOUT=30
GRANTBOT_HTTP_RETRIES=3
GRANTBOT_HTTP_BACKOFF=0.8
GRANTBOT_MAX_RESPONSE_MB=15
GRANTBOT_DISCOVERY_DELAY=0.35

# Optional broad web search.
# Grants.gov does NOT require this.
GRANTBOT_BRAVE_ENABLED=0
BRAVE_SEARCH_API_KEY=
BRAVE_ALLOW_STORAGE=0
ENV
fi

if [ -f "$ROOT/.env" ]; then
    if ! grep -q '^GRANTBOT_HTTP_CACHE_SECONDS=' "$ROOT/.env"; then
        cat >> "$ROOT/.env" <<'ENV'

GRANTBOT_HTTP_CACHE_SECONDS=900
GRANTBOT_HTTP_TIMEOUT=30
GRANTBOT_HTTP_RETRIES=3
GRANTBOT_HTTP_BACKOFF=0.8
GRANTBOT_MAX_RESPONSE_MB=15
GRANTBOT_DISCOVERY_DELAY=0.35

GRANTBOT_BRAVE_ENABLED=0
BRAVE_SEARCH_API_KEY=
BRAVE_ALLOW_STORAGE=0
ENV
    fi
fi

# ==============================================================
# DISCOVERY DATABASE SCHEMA
# ==============================================================

cat > "$ROOT/grantbot/discovery/schema.py" <<'PY'
from __future__ import annotations

from grantbot.core.database import connection


SCHEMA = """
CREATE TABLE IF NOT EXISTS discovery_source_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_id INTEGER NOT NULL,

    page_name TEXT,

    page_type TEXT NOT NULL DEFAULT 'HTML'
        CHECK (
            page_type IN (
                'HTML',
                'RSS',
                'JSON'
            )
        ),

    url TEXT NOT NULL UNIQUE,

    active INTEGER DEFAULT 1,

    respect_robots INTEGER DEFAULT 1,

    max_links INTEGER DEFAULT 100,

    metadata_json TEXT,

    created_at TEXT NOT NULL,

    updated_at TEXT NOT NULL,

    FOREIGN KEY(source_id)
        REFERENCES funding_sources(id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    mode TEXT NOT NULL,

    started_at TEXT NOT NULL,

    finished_at TEXT,

    sources_attempted INTEGER DEFAULT 0,

    queries_attempted INTEGER DEFAULT 0,

    results_seen INTEGER DEFAULT 0,

    opportunities_saved INTEGER DEFAULT 0,

    duplicates_skipped INTEGER DEFAULT 0,

    errors INTEGER DEFAULT 0,

    metadata_json TEXT
);


CREATE TABLE IF NOT EXISTS discovery_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    run_id INTEGER,

    source_key TEXT,

    query_text TEXT,

    event_type TEXT NOT NULL,

    message TEXT,

    metadata_json TEXT,

    created_at TEXT NOT NULL,

    FOREIGN KEY(run_id)
        REFERENCES discovery_runs(id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS opportunity_fingerprints (
    opportunity_id INTEGER PRIMARY KEY,

    fingerprint TEXT NOT NULL UNIQUE,

    created_at TEXT NOT NULL,

    FOREIGN KEY(opportunity_id)
        REFERENCES opportunities(id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS discovery_page_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    url TEXT NOT NULL UNIQUE,

    title TEXT,

    content_type TEXT,

    status_code INTEGER,

    sha256 TEXT,

    fetched_at TEXT NOT NULL,

    metadata_json TEXT
);


CREATE INDEX IF NOT EXISTS idx_discovery_pages_source
ON discovery_source_pages(source_id);

CREATE INDEX IF NOT EXISTS idx_discovery_runs_started
ON discovery_runs(started_at);

CREATE INDEX IF NOT EXISTS idx_discovery_events_run
ON discovery_events(run_id);

CREATE INDEX IF NOT EXISTS idx_discovery_events_source
ON discovery_events(source_key);
"""


def initialize_discovery_schema() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)
PY

# ==============================================================
# FILE CACHE
# ==============================================================

cat > "$ROOT/grantbot/discovery/cache.py" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import time

from pathlib import Path
from typing import Any

from grantbot.core.config import settings


class FileCache:

    def __init__(
        self,
        directory: Path | None = None,
    ):
        self.directory = (
            directory
            or settings.data_dir
            / "cache"
            / "http"
        )

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    @staticmethod
    def key_for(
        method: str,
        url: str,
        payload: Any = None,
    ) -> str:

        blob = json.dumps(
            {
                "method":
                    method.upper(),

                "url":
                    url,

                "payload":
                    payload,
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")

        return hashlib.sha256(
            blob
        ).hexdigest()

    def _path(
        self,
        key: str,
    ) -> Path:

        return (
            self.directory
            / f"{key}.json"
        )

    def get(
        self,
        key: str,
        ttl: int,
    ) -> dict | None:

        path = self._path(
            key
        )

        if not path.exists():
            return None

        try:
            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            created = float(
                payload.get(
                    "created",
                    0,
                )
            )

            if (
                ttl >= 0
                and time.time()
                - created
                > ttl
            ):
                try:
                    path.unlink()
                except OSError:
                    pass

                return None

            return payload.get(
                "value"
            )

        except Exception:
            try:
                path.unlink()
            except OSError:
                pass

            return None

    def set(
        self,
        key: str,
        value: dict,
    ) -> None:

        path = self._path(
            key
        )

        temp = path.with_suffix(
            ".tmp"
        )

        temp.write_text(
            json.dumps(
                {
                    "created":
                        time.time(),

                    "value":
                        value,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        os.replace(
            temp,
            path,
        )

    def clear(self) -> int:

        count = 0

        for path in self.directory.glob(
            "*.json"
        ):
            try:
                path.unlink()
                count += 1

            except OSError:
                pass

        return count
PY

# ==============================================================
# RESILIENT HTTP CLIENT
# ==============================================================

cat > "$ROOT/grantbot/discovery/http.py" <<'PY'
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
PY

# ==============================================================
# ROBOTS HANDLING
# ==============================================================

cat > "$ROOT/grantbot/discovery/robots.py" <<'PY'
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
PY

# ==============================================================
# DISCOVERY TEXT / MONEY / DEADLINE EXTRACTION
# ==============================================================

cat > "$ROOT/grantbot/discovery/extract.py" <<'PY'
from __future__ import annotations

import re

from datetime import datetime
from typing import Iterable

from grantbot.core.utils import (
    normalize_text,
)


FUNDING_MARKERS = (
    "grant",
    "funding",
    "fund",
    "request for proposals",
    "request for applications",
    "rfa",
    "rfp",
    "notice of funding",
    "nofo",
    "application",
    "applicants",
    "award",
    "opportunity",
    "sponsorship",
    "community investment",
    "impact investment",
    "program related investment",
    "recoverable grant",
)


MISSION_MARKERS = (
    "reentry",
    "returning citizen",
    "incarceration",
    "justice involved",
    "homeless",
    "homelessness",
    "housing",
    "affordable housing",
    "supportive housing",
    "workforce",
    "job training",
    "employment",
    "community development",
    "economic mobility",
    "poverty",
    "capital",
    "construction",
)


DATE_PATTERNS = (
    r"(?:deadline|due date|application deadline|closing date)"
    r"\s*(?:is|:|-)?\s*"
    r"([A-Z][a-z]+ \d{1,2},? \d{4})",

    r"(?:deadline|due date|application deadline|closing date)"
    r"\s*(?:is|:|-)?\s*"
    r"(\d{1,2}/\d{1,2}/\d{2,4})",

    r"(?:deadline|due date|application deadline|closing date)"
    r"\s*(?:is|:|-)?\s*"
    r"(\d{4}-\d{2}-\d{2})",
)


MONEY_PATTERN = re.compile(
    r"\$\s*"
    r"([0-9]{1,3}"
    r"(?:,[0-9]{3})*"
    r"(?:\.[0-9]{1,2})?)"
)


def funding_relevance(
    text: str,
    query: str = "",
) -> int:

    text_lower = (
        normalize_text(
            text
        ).lower()
    )

    query_lower = (
        normalize_text(
            query
        ).lower()
    )

    score = 0

    for marker in FUNDING_MARKERS:

        if marker in text_lower:
            score += 3

    for marker in MISSION_MARKERS:

        if marker in text_lower:
            score += 2

    if query_lower:

        if query_lower in text_lower:
            score += 8

        else:
            tokens = [
                token
                for token in re.findall(
                    r"[a-z0-9]+",
                    query_lower,
                )
                if len(token) >= 4
            ]

            matches = sum(
                1
                for token in tokens
                if token in text_lower
            )

            score += min(
                matches,
                6,
            )

    return score


def extract_deadline(
    text: str,
) -> str | None:

    text = normalize_text(
        text
    )

    for pattern in DATE_PATTERNS:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(
                1
            )

    return None


def extract_amounts(
    text: str,
) -> list[float]:

    amounts = []

    for match in MONEY_PATTERN.finditer(
        text
    ):

        try:
            amount = float(
                match.group(
                    1
                ).replace(
                    ",",
                    "",
                )
            )

        except ValueError:
            continue

        amounts.append(
            amount
        )

    return amounts


def extract_award_range(
    text: str,
) -> tuple[
    float | None,
    float | None,
]:

    amounts = extract_amounts(
        text
    )

    if not amounts:
        return (
            None,
            None,
        )

    return (
        min(amounts),
        max(amounts),
    )


def extract_eligibility_snippet(
    text: str,
) -> str | None:

    clean = normalize_text(
        text
    )

    patterns = (
        r"eligible applicants?.{0,500}",
        r"eligibility.{0,500}",
        r"who may apply.{0,500}",
        r"applicant eligibility.{0,500}",
    )

    for pattern in patterns:

        match = re.search(
            pattern,
            clean,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(
                0
            )[:600]

    return None
PY

# ==============================================================
# FINGERPRINT / DEDUPLICATION
# ==============================================================

cat > "$ROOT/grantbot/discovery/dedupe.py" <<'PY'
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
PY

# ==============================================================
# REGISTER / MANAGE OFFICIAL FUNDING PAGES
# ==============================================================

cat > "$ROOT/grantbot/discovery/pages.py" <<'PY'
from __future__ import annotations

from grantbot.core.database import (
    connection,
    utc_now,
)

from grantbot.core.utils import (
    safe_json_dumps,
    safe_json_loads,
)

from grantbot.funding.registry import (
    get_source,
)

from grantbot.discovery.schema import (
    initialize_discovery_schema,
)


def add_page(
    *,
    source_key: str,
    url: str,
    page_name: str | None = None,
    page_type: str = "HTML",
    respect_robots: bool = True,
    max_links: int = 100,
    metadata: dict | None = None,
) -> dict:

    initialize_discovery_schema()

    source = get_source(
        source_key
    )

    if not source:
        raise ValueError(
            f"Unknown funding source: "
            f"{source_key}"
        )

    page_type = (
        page_type.upper()
    )

    if page_type not in {
        "HTML",
        "RSS",
        "JSON",
    }:
        raise ValueError(
            "page_type must be "
            "HTML, RSS, or JSON"
        )

    now = utc_now()

    with connection() as conn:

        existing = conn.execute(
            """
            SELECT id
            FROM discovery_source_pages
            WHERE url=?
            """,
            (url,),
        ).fetchone()

        if existing:

            page_id = (
                existing["id"]
            )

            conn.execute(
                """
                UPDATE discovery_source_pages
                SET
                    source_id=?,
                    page_name=?,
                    page_type=?,
                    active=1,
                    respect_robots=?,
                    max_links=?,
                    metadata_json=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    source["id"],
                    page_name,
                    page_type,
                    1
                    if respect_robots
                    else 0,
                    int(
                        max_links
                    ),
                    safe_json_dumps(
                        metadata
                        or {}
                    ),
                    now,
                    page_id,
                ),
            )

        else:

            cursor = conn.execute(
                """
                INSERT INTO discovery_source_pages(
                    source_id,
                    page_name,
                    page_type,
                    url,
                    active,
                    respect_robots,
                    max_links,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?,
                    1, ?, ?, ?, ?, ?
                )
                """,
                (
                    source["id"],
                    page_name,
                    page_type,
                    url,
                    1
                    if respect_robots
                    else 0,
                    int(
                        max_links
                    ),
                    safe_json_dumps(
                        metadata
                        or {}
                    ),
                    now,
                    now,
                ),
            )

            page_id = (
                cursor.lastrowid
            )

    return get_page(
        page_id
    )


def get_page(
    page_id: int,
) -> dict | None:

    with connection() as conn:

        row = conn.execute(
            """
            SELECT
                p.*,
                sp.source_key,
                fs.source_name
            FROM discovery_source_pages p
            JOIN funding_source_profiles sp
              ON sp.source_id=p.source_id
            JOIN funding_sources fs
              ON fs.id=p.source_id
            WHERE p.id=?
            """,
            (page_id,),
        ).fetchone()

    if not row:
        return None

    result = dict(
        row
    )

    result["metadata"] = (
        safe_json_loads(
            result.get(
                "metadata_json"
            ),
            {},
        )
    )

    return result


def list_pages(
    source_key: str | None = None,
    *,
    active_only: bool = True,
) -> list[dict]:

    sql = """
        SELECT
            p.*,
            sp.source_key,
            fs.source_name
        FROM discovery_source_pages p
        JOIN funding_source_profiles sp
          ON sp.source_id=p.source_id
        JOIN funding_sources fs
          ON fs.id=p.source_id
        WHERE 1=1
    """

    params = []

    if source_key:
        sql += """
            AND sp.source_key=?
        """

        params.append(
            source_key
        )

    if active_only:
        sql += """
            AND p.active=1
        """

    sql += """
        ORDER BY
            sp.source_key,
            p.page_name,
            p.url
    """

    with connection() as conn:

        rows = conn.execute(
            sql,
            tuple(params),
        ).fetchall()

    results = []

    for row in rows:

        record = dict(
            row
        )

        record["metadata"] = (
            safe_json_loads(
                record.get(
                    "metadata_json"
                ),
                {},
            )
        )

        results.append(
            record
        )

    return results


def remove_page(
    page_id: int,
) -> bool:

    with connection() as conn:

        cursor = conn.execute(
            """
            DELETE FROM discovery_source_pages
            WHERE id=?
            """,
            (page_id,),
        )

        return (
            cursor.rowcount
            > 0
        )
PY

# ==============================================================
# GRANTS.GOV LIVE CONNECTOR
# ==============================================================

cat > "$ROOT/grantbot/funding/connectors/grants_gov.py" <<'PY'
from __future__ import annotations

from typing import Iterable

from grantbot.core.errors import (
    ExternalServiceError,
)

from grantbot.core.utils import (
    normalize_text,
)

from grantbot.discovery.http import (
    HttpClient,
)

from grantbot.funding.adapters import (
    FundingSourceAdapter,
    SearchRequest,
    SearchResult,
)


SEARCH_URL = (
    "https://api.grants.gov/"
    "v1/api/search2"
)

DETAIL_URL = (
    "https://api.grants.gov/"
    "v1/api/fetchOpportunity"
)


ATTRIBUTION = (
    "This product uses the Grants.gov API "
    "but is not endorsed or certified by "
    "the U.S. Department of Health and "
    "Human Services."
)


def _float_or_none(
    value,
):
    if value is None:
        return None

    text = (
        str(value)
        .replace(
            "$",
            "",
        )
        .replace(
            ",",
            "",
        )
        .strip()
    )

    if not text:
        return None

    try:
        return float(
            text
        )

    except ValueError:
        return None


class GrantsGovAdapter(
    FundingSourceAdapter
):

    source_key = (
        "federal_grants_gov"
    )

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        enrich_details: bool = True,
        detail_limit: int = 10,
    ):

        self.client = (
            client
            or HttpClient()
        )

        self.enrich_details = (
            enrich_details
        )

        self.detail_limit = max(
            0,
            int(
                detail_limit
            ),
        )

    def fetch_detail(
        self,
        opportunity_id: str | int,
    ) -> dict:

        payload = {
            "opportunityId":
                int(
                    opportunity_id
                )
        }

        result = (
            self.client.post_json(
                DETAIL_URL,
                json_body=payload,
            )
        )

        if int(
            result.get(
                "errorcode",
                0,
            )
        ) != 0:
            raise ExternalServiceError(
                "Grants.gov fetchOpportunity "
                f"failed: {result.get('msg')}"
            )

        return (
            result.get(
                "data"
            )
            or {}
        )

    def search(
        self,
        request: SearchRequest,
    ) -> Iterable[SearchResult]:

        filters = dict(
            request.filters
            or {}
        )

        rows = min(
            max(
                int(
                    request.limit
                ),
                1,
            ),
            100,
        )

        payload = {
            "rows":
                rows,

            "keyword":
                request.query,

            "oppStatuses":
                filters.pop(
                    "oppStatuses",
                    (
                        "forecasted|posted"
                    ),
                ),
        }

        allowed = {
            "oppNum",
            "eligibilities",
            "agencies",
            "aln",
            "fundingCategories",
            "fundingInstruments",
            "startRecordNum",
            "sortBy",
        }

        for key, value in (
            filters.items()
        ):
            if (
                key in allowed
                and value not in (
                    None,
                    "",
                )
            ):
                payload[key] = (
                    value
                )

        result = (
            self.client.post_json(
                SEARCH_URL,
                json_body=payload,
            )
        )

        if int(
            result.get(
                "errorcode",
                0,
            )
        ) != 0:
            raise ExternalServiceError(
                "Grants.gov search2 failed: "
                f"{result.get('msg')}"
            )

        data = (
            result.get(
                "data"
            )
            or {}
        )

        hits = (
            data.get(
                "oppHits"
            )
            or []
        )

        for index, hit in enumerate(
            hits[:rows]
        ):

            opportunity_id = (
                hit.get(
                    "id"
                )
            )

            detail = {}

            if (
                self.enrich_details
                and opportunity_id
                and index
                < self.detail_limit
            ):
                try:
                    detail = (
                        self.fetch_detail(
                            opportunity_id
                        )
                    )
                except Exception:
                    detail = {}

            synopsis = (
                detail.get(
                    "synopsis"
                )
                or {}
            )

            applicant_types = (
                synopsis.get(
                    "applicantTypes"
                )
                or []
            )

            eligibility = "; ".join(
                normalize_text(
                    row.get(
                        "description"
                    )
                )
                for row
                in applicant_types
                if row.get(
                    "description"
                )
            )

            description = (
                synopsis.get(
                    "synopsisDesc"
                )
                or ""
            )

            agency_name = (
                hit.get(
                    "agencyName"
                )
                or synopsis.get(
                    "agencyName"
                )
                or (
                    detail.get(
                        "agencyDetails"
                    )
                    or {}
                ).get(
                    "agencyName"
                )
            )

            raw = {
                "search_hit":
                    hit,

                "detail":
                    detail,

                "grants_gov_attribution":
                    ATTRIBUTION,
            }

            yield SearchResult(
                external_id=(
                    str(
                        opportunity_id
                    )
                    if opportunity_id
                    is not None
                    else hit.get(
                        "number"
                    )
                ),

                title=(
                    hit.get(
                        "title"
                    )
                    or detail.get(
                        "opportunityTitle"
                    )
                    or "Untitled federal opportunity"
                ),

                description=(
                    normalize_text(
                        description
                    )
                    or None
                ),

                eligibility=(
                    eligibility
                    or None
                ),

                funder=(
                    agency_name
                ),

                agency=(
                    agency_name
                ),

                geography=(
                    "United States"
                ),

                deadline=(
                    hit.get(
                        "closeDate"
                    )
                    or detail.get(
                        "originalDueDateDesc"
                    )
                    or None
                ),

                award_floor=(
                    _float_or_none(
                        synopsis.get(
                            "awardFloor"
                        )
                    )
                ),

                award_ceiling=(
                    _float_or_none(
                        synopsis.get(
                            "awardCeiling"
                        )
                    )
                ),

                source_url=(
                    "https://www.grants.gov/"
                    "search-results-detail/"
                    f"{opportunity_id}"
                    if opportunity_id
                    else "https://www.grants.gov"
                ),

                raw=raw,
            )
PY

# ==============================================================
# OFFICIAL HTML FUNDING-PAGE CONNECTOR
# ==============================================================

cat > "$ROOT/grantbot/funding/connectors/html_page.py" <<'PY'
from __future__ import annotations

from urllib.parse import (
    urljoin,
    urlparse,
)

from bs4 import BeautifulSoup

from grantbot.core.utils import (
    normalize_text,
)

from grantbot.discovery.extract import (
    extract_award_range,
    extract_deadline,
    extract_eligibility_snippet,
    funding_relevance,
)

from grantbot.discovery.http import (
    HttpClient,
)

from grantbot.discovery.robots import (
    can_fetch,
)

from grantbot.funding.adapters import (
    FundingSourceAdapter,
    SearchRequest,
    SearchResult,
)


class OfficialFundingPageAdapter(
    FundingSourceAdapter
):

    def __init__(
        self,
        *,
        source_key: str,
        pages: list[dict],
        client: HttpClient | None = None,
    ):

        self.source_key = (
            source_key
        )

        self.pages = (
            pages
        )

        self.client = (
            client
            or HttpClient()
        )

    def search(
        self,
        request: SearchRequest,
    ):

        seen = set()

        result_count = 0

        for page in self.pages:

            if (
                result_count
                >= request.limit
            ):
                break

            page_url = (
                page["url"]
            )

            if (
                page.get(
                    "respect_robots",
                    1,
                )
                and not can_fetch(
                    page_url,
                    self.client,
                    self.client.user_agent,
                )
            ):
                continue

            html = (
                self.client.get_text(
                    page_url
                )
            )

            soup = BeautifulSoup(
                html,
                "html.parser",
            )

            max_links = int(
                page.get(
                    "max_links",
                    100,
                )
            )

            for anchor in soup.find_all(
                "a",
                href=True,
                limit=max_links,
            ):

                if (
                    result_count
                    >= request.limit
                ):
                    break

                href = urljoin(
                    page_url,
                    anchor.get(
                        "href"
                    ),
                )

                parsed = urlparse(
                    href
                )

                if parsed.scheme not in {
                    "http",
                    "https",
                }:
                    continue

                title = normalize_text(
                    anchor.get_text(
                        " ",
                        strip=True,
                    )
                )

                if not title:
                    title = (
                        parsed.path
                        .rstrip("/")
                        .split("/")[-1]
                        .replace(
                            "-",
                            " ",
                        )
                        .replace(
                            "_",
                            " ",
                        )
                    )

                parent = (
                    anchor.parent
                )

                context = normalize_text(
                    parent.get_text(
                        " ",
                        strip=True,
                    )
                    if parent
                    else title
                )

                material = (
                    f"{title} "
                    f"{context} "
                    f"{href}"
                )

                score = funding_relevance(
                    material,
                    request.query,
                )

                if score < 4:
                    continue

                dedupe_key = (
                    href.lower()
                )

                if dedupe_key in seen:
                    continue

                seen.add(
                    dedupe_key
                )

                floor, ceiling = (
                    extract_award_range(
                        context
                    )
                )

                yield SearchResult(
                    external_id=None,

                    title=title,

                    description=(
                        context[:1000]
                        or None
                    ),

                    eligibility=(
                        extract_eligibility_snippet(
                            context
                        )
                    ),

                    funder=(
                        page.get(
                            "source_name"
                        )
                    ),

                    agency=(
                        page.get(
                            "source_name"
                        )
                    ),

                    geography=(
                        request.geography
                    ),

                    deadline=(
                        extract_deadline(
                            context
                        )
                    ),

                    award_floor=floor,

                    award_ceiling=ceiling,

                    source_url=href,

                    raw={
                        "discovery_method":
                            "official_page",

                        "listing_page":
                            page_url,

                        "relevance_score":
                            score,
                    },
                )

                result_count += 1
PY

# ==============================================================
# RSS CONNECTOR
# ==============================================================

cat > "$ROOT/grantbot/funding/connectors/rss.py" <<'PY'
from __future__ import annotations

import xml.etree.ElementTree as ET

from grantbot.core.utils import (
    normalize_text,
)

from grantbot.discovery.extract import (
    extract_award_range,
    extract_deadline,
    extract_eligibility_snippet,
    funding_relevance,
)

from grantbot.discovery.http import (
    HttpClient,
)

from grantbot.funding.adapters import (
    FundingSourceAdapter,
    SearchRequest,
    SearchResult,
)


def _text(
    element,
    names,
):
    for name in names:

        child = element.find(
            name
        )

        if (
            child is not None
            and child.text
        ):
            return normalize_text(
                child.text
            )

    return ""


class RSSFundingAdapter(
    FundingSourceAdapter
):

    def __init__(
        self,
        *,
        source_key: str,
        pages: list[dict],
        client: HttpClient | None = None,
    ):

        self.source_key = source_key

        self.pages = pages

        self.client = (
            client
            or HttpClient()
        )

    def search(
        self,
        request: SearchRequest,
    ):

        yielded = 0

        for page in self.pages:

            if (
                yielded
                >= request.limit
            ):
                break

            xml_text = (
                self.client.get_text(
                    page["url"]
                )
            )

            root = ET.fromstring(
                xml_text
            )

            items = list(
                root.findall(
                    ".//item"
                )
            )

            if not items:
                items = list(
                    root.findall(
                        ".//{*}entry"
                    )
                )

            for item in items:

                if (
                    yielded
                    >= request.limit
                ):
                    break

                title = _text(
                    item,
                    (
                        "title",
                        "{*}title",
                    ),
                )

                description = _text(
                    item,
                    (
                        "description",
                        "summary",
                        "{*}summary",
                        "{*}content",
                    ),
                )

                link = _text(
                    item,
                    (
                        "link",
                        "{*}link",
                    ),
                )

                if not link:

                    link_node = (
                        item.find(
                            "{*}link"
                        )
                    )

                    if (
                        link_node
                        is not None
                    ):
                        link = (
                            link_node.attrib.get(
                                "href",
                                "",
                            )
                        )

                material = (
                    f"{title} "
                    f"{description}"
                )

                score = funding_relevance(
                    material,
                    request.query,
                )

                if score < 4:
                    continue

                floor, ceiling = (
                    extract_award_range(
                        description
                    )
                )

                yield SearchResult(
                    external_id=None,

                    title=(
                        title
                        or "Funding opportunity"
                    ),

                    description=(
                        description
                        or None
                    ),

                    eligibility=(
                        extract_eligibility_snippet(
                            description
                        )
                    ),

                    funder=(
                        page.get(
                            "source_name"
                        )
                    ),

                    agency=(
                        page.get(
                            "source_name"
                        )
                    ),

                    geography=(
                        request.geography
                    ),

                    deadline=(
                        extract_deadline(
                            description
                        )
                    ),

                    award_floor=floor,

                    award_ceiling=ceiling,

                    source_url=(
                        link
                        or page["url"]
                    ),

                    raw={
                        "discovery_method":
                            "rss",

                        "feed":
                            page["url"],

                        "relevance_score":
                            score,
                    },
                )

                yielded += 1
PY

# ==============================================================
# OPTIONAL BRAVE SEARCH PROVIDER
# ==============================================================

cat > "$ROOT/grantbot/discovery/brave.py" <<'PY'
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
PY

# ==============================================================
# WEB PAGE ANALYZER
# ==============================================================

cat > "$ROOT/grantbot/discovery/page_analyzer.py" <<'PY'
from __future__ import annotations

from bs4 import BeautifulSoup

from grantbot.core.utils import (
    normalize_text,
)

from grantbot.discovery.extract import (
    extract_award_range,
    extract_deadline,
    extract_eligibility_snippet,
    funding_relevance,
)

from grantbot.discovery.robots import (
    can_fetch,
)

from grantbot.funding.adapters import (
    SearchResult,
)


def analyze_live_page(
    *,
    url: str,
    source_key: str,
    source_name: str,
    query: str,
    geography: str | None,
    client,
    search_title: str | None = None,
    respect_robots: bool = True,
) -> SearchResult | None:

    if (
        respect_robots
        and not can_fetch(
            url,
            client,
            client.user_agent,
        )
    ):
        return None

    response = client.request(
        "GET",
        url,
    )

    content_type = (
        response.headers.get(
            "Content-Type",
            ""
        ).lower()
    )

    if (
        "text/html"
        not in content_type
        and "<html"
        not in response.text[
            :500
        ].lower()
    ):
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg",
    ]):
        tag.decompose()

    title = ""

    if soup.title:
        title = normalize_text(
            soup.title.get_text(
                " ",
                strip=True,
            )
        )

    if not title:
        title = (
            search_title
            or "Funding opportunity"
        )

    text = normalize_text(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    if len(text) > 150000:
        text = text[:150000]

    relevance = funding_relevance(
        (
            f"{title} "
            f"{text}"
        ),
        query,
    )

    if relevance < 8:
        return None

    floor, ceiling = (
        extract_award_range(
            text
        )
    )

    return SearchResult(
        external_id=None,

        title=title[:500],

        description=(
            text[:1800]
            or None
        ),

        eligibility=(
            extract_eligibility_snippet(
                text
            )
        ),

        funder=source_name,

        agency=source_name,

        geography=geography,

        deadline=(
            extract_deadline(
                text
            )
        ),

        award_floor=floor,

        award_ceiling=ceiling,

        source_url=url,

        raw={
            "discovery_method":
                "web_page_analysis",

            "source_key":
                source_key,

            "relevance_score":
                relevance,

            "content_type":
                content_type,
        },
    )
PY

# ==============================================================
# WEB QUERY INTELLIGENCE
# ==============================================================

cat > "$ROOT/grantbot/discovery/query_builder.py" <<'PY'
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
PY

# ==============================================================
# DISCOVERY RUN AUDIT
# ==============================================================

cat > "$ROOT/grantbot/discovery/runs.py" <<'PY'
from __future__ import annotations

from grantbot.core.database import (
    connection,
    utc_now,
)

from grantbot.core.utils import (
    safe_json_dumps,
)


def start_run(
    mode: str,
    metadata: dict | None = None,
) -> int:

    with connection() as conn:

        cursor = conn.execute(
            """
            INSERT INTO discovery_runs(
                mode,
                started_at,
                metadata_json
            )
            VALUES (?, ?, ?)
            """,
            (
                mode,
                utc_now(),
                safe_json_dumps(
                    metadata
                    or {}
                ),
            ),
        )

        return int(
            cursor.lastrowid
        )


def finish_run(
    run_id: int,
    *,
    sources_attempted: int,
    queries_attempted: int,
    results_seen: int,
    opportunities_saved: int,
    duplicates_skipped: int,
    errors: int,
) -> None:

    with connection() as conn:

        conn.execute(
            """
            UPDATE discovery_runs
            SET
                finished_at=?,
                sources_attempted=?,
                queries_attempted=?,
                results_seen=?,
                opportunities_saved=?,
                duplicates_skipped=?,
                errors=?
            WHERE id=?
            """,
            (
                utc_now(),
                sources_attempted,
                queries_attempted,
                results_seen,
                opportunities_saved,
                duplicates_skipped,
                errors,
                run_id,
            ),
        )


def event(
    run_id: int,
    *,
    event_type: str,
    source_key: str | None = None,
    query_text: str | None = None,
    message: str | None = None,
    metadata: dict | None = None,
) -> None:

    with connection() as conn:

        conn.execute(
            """
            INSERT INTO discovery_events(
                run_id,
                source_key,
                query_text,
                event_type,
                message,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                source_key,
                query_text,
                event_type,
                message,
                safe_json_dumps(
                    metadata
                    or {}
                ),
                utc_now(),
            ),
        )
PY

# ==============================================================
# LIVE DISCOVERY ENGINE
# ==============================================================

cat > "$ROOT/grantbot/discovery/engine.py" <<'PY'
from __future__ import annotations

import hashlib
import json

from urllib.parse import urlparse

from grantbot.core.database import (
    connection,
    utc_now,
)

from grantbot.core.logging_config import (
    get_logger,
)

from grantbot.discovery.brave import (
    BraveSearchProvider,
)

from grantbot.discovery.dedupe import (
    fingerprint,
    fingerprint_exists,
    store_fingerprint,
)

from grantbot.discovery.http import (
    HttpClient,
)

from grantbot.discovery.page_analyzer import (
    analyze_live_page,
)

from grantbot.discovery.pages import (
    list_pages,
)

from grantbot.discovery.query_builder import (
    build_web_query,
)

from grantbot.discovery.runs import (
    event,
    finish_run,
    start_run,
)

from grantbot.funding.adapters import (
    SearchRequest,
)

from grantbot.funding.connectors.grants_gov import (
    GrantsGovAdapter,
)

from grantbot.funding.connectors.html_page import (
    OfficialFundingPageAdapter,
)

from grantbot.funding.connectors.rss import (
    RSSFundingAdapter,
)

from grantbot.funding.ingest import (
    ingest_opportunity,
)

from grantbot.funding.registry import (
    get_source,
)


logger = get_logger(
    "discovery.engine"
)


class DiscoveryEngine:

    def __init__(
        self,
        *,
        client: HttpClient | None = None,
    ):

        self.client = (
            client
            or HttpClient()
        )

        self.brave = (
            BraveSearchProvider(
                client=self.client
            )
        )

    @staticmethod
    def _synthetic_external_id(
        source_key: str,
        result,
    ) -> str:

        material = "|".join([
            source_key,
            str(
                result.source_url
                or ""
            ),
            str(
                result.title
                or ""
            ),
            str(
                result.deadline
                or ""
            ),
        ])

        return (
            "gb-"
            + hashlib.sha256(
                material.encode(
                    "utf-8"
                )
            ).hexdigest()[:24]
        )

    def save_result(
        self,
        *,
        source_key: str,
        result,
        lane: str | None = None,
    ) -> tuple[
        int | None,
        bool,
    ]:

        external_id = (
            result.external_id
            or self._synthetic_external_id(
                source_key,
                result,
            )
        )

        fp = fingerprint(
            source_key=source_key,
            title=result.title,
            source_url=result.source_url,
            external_id=external_id,
            deadline=result.deadline,
        )

        if fingerprint_exists(
            fp
        ):
            return (
                None,
                True,
            )

        raw = dict(
            result.raw
            or {}
        )

        if lane:
            raw[
                "grantbot_lane"
            ] = lane

        opportunity_id = (
            ingest_opportunity(
                source_key,
                {
                    "external_id":
                        external_id,

                    "opportunity_type":
                        (
                            "GRANT"
                            if source_key
                            != "angel_investors"
                            else "INVESTMENT"
                        ),

                    "title":
                        result.title,

                    "funder":
                        result.funder,

                    "agency":
                        result.agency,

                    "description":
                        result.description,

                    "eligibility":
                        result.eligibility,

                    "geography":
                        result.geography,

                    "deadline":
                        result.deadline,

                    "award_floor":
                        result.award_floor,

                    "award_ceiling":
                        result.award_ceiling,

                    "source_url":
                        result.source_url,

                    "status":
                        "DISCOVERED",

                    "raw":
                        raw,
                },
            )
        )

        store_fingerprint(
            opportunity_id,
            fp,
        )

        if lane:

            with connection() as conn:

                conn.execute(
                    """
                    INSERT OR IGNORE
                    INTO opportunity_tags(
                        opportunity_id,
                        tag
                    )
                    VALUES (?, ?)
                    """,
                    (
                        opportunity_id,
                        lane,
                    ),
                )

        return (
            opportunity_id,
            False,
        )

    def grants_gov(
        self,
        *,
        query: str,
        limit: int = 25,
        detail_limit: int = 10,
        save: bool = True,
        filters: dict | None = None,
        lane: str | None = None,
    ) -> dict:

        run_id = start_run(
            "GRANTS_GOV",
            {
                "query":
                    query,
            },
        )

        stats = {
            "run_id":
                run_id,

            "results":
                [],

            "seen":
                0,

            "saved":
                0,

            "duplicates":
                0,

            "errors":
                0,
        }

        adapter = GrantsGovAdapter(
            self.client,
            enrich_details=True,
            detail_limit=detail_limit,
        )

        try:

            request = SearchRequest(
                query=query,
                geography=(
                    "United States"
                ),
                limit=limit,
                filters=filters,
            )

            for result in adapter.search(
                request
            ):

                stats["seen"] += 1

                record = {
                    "external_id":
                        result.external_id,

                    "title":
                        result.title,

                    "agency":
                        result.agency,

                    "deadline":
                        result.deadline,

                    "award_floor":
                        result.award_floor,

                    "award_ceiling":
                        result.award_ceiling,

                    "source_url":
                        result.source_url,
                }

                if save:

                    opportunity_id, duplicate = (
                        self.save_result(
                            source_key=(
                                "federal_grants_gov"
                            ),
                            result=result,
                            lane=lane,
                        )
                    )

                    record[
                        "opportunity_id"
                    ] = opportunity_id

                    record[
                        "duplicate"
                    ] = duplicate

                    if duplicate:
                        stats[
                            "duplicates"
                        ] += 1
                    else:
                        stats[
                            "saved"
                        ] += 1

                stats[
                    "results"
                ].append(
                    record
                )

        except Exception as exc:

            stats["errors"] += 1

            event(
                run_id,
                event_type="ERROR",
                source_key=(
                    "federal_grants_gov"
                ),
                query_text=query,
                message=str(exc),
            )

            raise

        finally:

            finish_run(
                run_id,
                sources_attempted=1,
                queries_attempted=1,
                results_seen=(
                    stats["seen"]
                ),
                opportunities_saved=(
                    stats["saved"]
                ),
                duplicates_skipped=(
                    stats["duplicates"]
                ),
                errors=(
                    stats["errors"]
                ),
            )

        return stats

    def crawl_registered_pages(
        self,
        *,
        source_key: str,
        query: str,
        geography: str | None = None,
        limit: int = 25,
        save: bool = True,
        lane: str | None = None,
    ) -> dict:

        pages = list_pages(
            source_key
        )

        html_pages = [
            page
            for page in pages
            if page[
                "page_type"
            ] == "HTML"
        ]

        rss_pages = [
            page
            for page in pages
            if page[
                "page_type"
            ] == "RSS"
        ]

        run_id = start_run(
            "REGISTERED_PAGES",
            {
                "source_key":
                    source_key,

                "query":
                    query,
            },
        )

        stats = {
            "run_id":
                run_id,

            "pages":
                len(pages),

            "seen":
                0,

            "saved":
                0,

            "duplicates":
                0,

            "errors":
                0,

            "results":
                [],
        }

        adapters = []

        if html_pages:
            adapters.append(
                OfficialFundingPageAdapter(
                    source_key=source_key,
                    pages=html_pages,
                    client=self.client,
                )
            )

        if rss_pages:
            adapters.append(
                RSSFundingAdapter(
                    source_key=source_key,
                    pages=rss_pages,
                    client=self.client,
                )
            )

        try:

            for adapter in adapters:

                request = SearchRequest(
                    query=query,
                    geography=geography,
                    limit=limit,
                )

                for result in adapter.search(
                    request
                ):

                    stats[
                        "seen"
                    ] += 1

                    if save:

                        opportunity_id, duplicate = (
                            self.save_result(
                                source_key=source_key,
                                result=result,
                                lane=lane,
                            )
                        )

                        if duplicate:
                            stats[
                                "duplicates"
                            ] += 1
                        else:
                            stats[
                                "saved"
                            ] += 1

                    else:

                        opportunity_id = (
                            None
                        )

                        duplicate = False

                    stats[
                        "results"
                    ].append({
                        "title":
                            result.title,

                        "source_url":
                            result.source_url,

                        "deadline":
                            result.deadline,

                        "opportunity_id":
                            opportunity_id,

                        "duplicate":
                            duplicate,
                    })

        except Exception as exc:

            stats[
                "errors"
            ] += 1

            event(
                run_id,
                event_type="ERROR",
                source_key=source_key,
                query_text=query,
                message=str(exc),
            )

            raise

        finally:

            finish_run(
                run_id,
                sources_attempted=(
                    len(
                        adapters
                    )
                ),
                queries_attempted=1,
                results_seen=(
                    stats[
                        "seen"
                    ]
                ),
                opportunities_saved=(
                    stats[
                        "saved"
                    ]
                ),
                duplicates_skipped=(
                    stats[
                        "duplicates"
                    ]
                ),
                errors=(
                    stats[
                        "errors"
                    ]
                ),
            )

        return stats

    def broad_web_search(
        self,
        *,
        plan_row: dict,
        count: int = 10,
        save: bool = True,
        max_pages: int = 6,
    ) -> dict:

        source_key = (
            plan_row[
                "source_key"
            ]
        )

        source = get_source(
            source_key
        )

        if not source:
            raise ValueError(
                f"Unknown source: "
                f"{source_key}"
            )

        web_query = (
            build_web_query(
                plan_row
            )
        )

        run_id = start_run(
            "WEB_SEARCH",
            {
                "query":
                    web_query,

                "source_key":
                    source_key,
            },
        )

        stats = {
            "run_id":
                run_id,

            "query":
                web_query,

            "candidates":
                0,

            "pages_analyzed":
                0,

            "seen":
                0,

            "saved":
                0,

            "duplicates":
                0,

            "errors":
                0,

            "results":
                [],
        }

        try:

            candidates = (
                self.brave.search(
                    web_query,
                    count=count,
                )
            )

            stats[
                "candidates"
            ] = len(
                candidates
            )

            for candidate in (
                candidates[
                    :max_pages
                ]
            ):

                url = (
                    candidate[
                        "url"
                    ]
                )

                try:

                    result = (
                        analyze_live_page(
                            url=url,
                            source_key=source_key,
                            source_name=source[
                                "source_name"
                            ],
                            query=(
                                plan_row[
                                    "query"
                                ]
                            ),
                            geography=(
                                plan_row.get(
                                    "geography"
                                )
                            ),
                            client=(
                                self.client
                            ),
                            search_title=(
                                candidate.get(
                                    "title"
                                )
                            ),
                        )
                    )

                    stats[
                        "pages_analyzed"
                    ] += 1

                except Exception as exc:

                    event(
                        run_id,
                        event_type=(
                            "PAGE_ERROR"
                        ),
                        source_key=(
                            source_key
                        ),
                        query_text=(
                            web_query
                        ),
                        message=(
                            f"{url}: {exc}"
                        ),
                    )

                    stats[
                        "errors"
                    ] += 1

                    continue

                if result is None:
                    continue

                stats[
                    "seen"
                ] += 1

                opportunity_id = None
                duplicate = False

                if save:

                    opportunity_id, duplicate = (
                        self.save_result(
                            source_key=(
                                source_key
                            ),
                            result=result,
                            lane=(
                                plan_row.get(
                                    "lane"
                                )
                            ),
                        )
                    )

                    if duplicate:

                        stats[
                            "duplicates"
                        ] += 1

                    else:

                        stats[
                            "saved"
                        ] += 1

                stats[
                    "results"
                ].append({
                    "title":
                        result.title,

                    "source_url":
                        result.source_url,

                    "deadline":
                        result.deadline,

                    "opportunity_id":
                        opportunity_id,

                    "duplicate":
                        duplicate,
                })

        except Exception as exc:

            stats[
                "errors"
            ] += 1

            event(
                run_id,
                event_type="ERROR",
                source_key=source_key,
                query_text=web_query,
                message=str(exc),
            )

            raise

        finally:

            finish_run(
                run_id,
                sources_attempted=1,
                queries_attempted=1,
                results_seen=(
                    stats[
                        "seen"
                    ]
                ),
                opportunities_saved=(
                    stats[
                        "saved"
                    ]
                ),
                duplicates_skipped=(
                    stats[
                        "duplicates"
                    ]
                ),
                errors=(
                    stats[
                        "errors"
                    ]
                ),
            )

        return stats
PY

# ==============================================================
# DISCOVERY PLAN RUNNER
# ==============================================================

cat > "$ROOT/grantbot/discovery/runner.py" <<'PY'
from __future__ import annotations

from grantbot.discovery.engine import (
    DiscoveryEngine,
)

from grantbot.discovery.pages import (
    list_pages,
)

from grantbot.funding.planner import (
    build_discovery_plan,
)


def run_discovery_plan(
    *,
    state: str = "Florida",
    counties: list[str] | None = None,
    cities: list[str] | None = None,
    lanes: list[str] | None = None,
    max_queries: int = 20,
    per_query_limit: int = 10,
    use_web: bool = False,
    save: bool = True,
) -> dict:

    engine = DiscoveryEngine()

    plan = build_discovery_plan(
        state=state,
        counties=counties,
        cities=cities,
        lanes=lanes,
        max_terms_per_lane=2,
    )

    summary = {
        "planned":
            len(plan),

        "executed":
            0,

        "saved":
            0,

        "duplicates":
            0,

        "errors":
            0,

        "skipped_no_connector":
            0,

        "runs":
            [],
    }

    seen_pairs = set()

    for row in plan:

        if (
            summary["executed"]
            >= max_queries
        ):
            break

        source_key = (
            row["source_key"]
        )

        pair = (
            source_key,
            row["query"],
        )

        if pair in seen_pairs:
            continue

        seen_pairs.add(
            pair
        )

        try:

            if (
                source_key
                == "federal_grants_gov"
            ):

                result = (
                    engine.grants_gov(
                        query=row[
                            "query"
                        ],
                        limit=(
                            per_query_limit
                        ),
                        detail_limit=min(
                            5,
                            per_query_limit,
                        ),
                        save=save,
                        lane=row[
                            "lane"
                        ],
                    )
                )

            else:

                pages = list_pages(
                    source_key
                )

                if pages:

                    result = (
                        engine.crawl_registered_pages(
                            source_key=source_key,
                            query=row[
                                "query"
                            ],
                            geography=row.get(
                                "geography"
                            ),
                            limit=(
                                per_query_limit
                            ),
                            save=save,
                            lane=row[
                                "lane"
                            ],
                        )
                    )

                elif (
                    use_web
                    and engine.brave.enabled
                ):

                    result = (
                        engine.broad_web_search(
                            plan_row=row,
                            count=min(
                                per_query_limit,
                                10,
                            ),
                            max_pages=min(
                                per_query_limit,
                                6,
                            ),
                            save=save,
                        )
                    )

                else:

                    summary[
                        "skipped_no_connector"
                    ] += 1

                    continue

            summary[
                "executed"
            ] += 1

            summary[
                "saved"
            ] += int(
                result.get(
                    "saved",
                    0,
                )
            )

            summary[
                "duplicates"
            ] += int(
                result.get(
                    "duplicates",
                    0,
                )
            )

            summary[
                "errors"
            ] += int(
                result.get(
                    "errors",
                    0,
                )
            )

            summary[
                "runs"
            ].append({
                "source_key":
                    source_key,

                "lane":
                    row[
                        "lane"
                    ],

                "query":
                    row[
                        "query"
                    ],

                "saved":
                    result.get(
                        "saved",
                        0,
                    ),

                "duplicates":
                    result.get(
                        "duplicates",
                        0,
                    ),
            })

        except Exception as exc:

            summary[
                "executed"
            ] += 1

            summary[
                "errors"
            ] += 1

            summary[
                "runs"
            ].append({
                "source_key":
                    source_key,

                "lane":
                    row[
                        "lane"
                    ],

                "query":
                    row[
                        "query"
                    ],

                "error":
                    str(exc),
            })

    return summary
PY

# ==============================================================
# DISCOVERY STATISTICS
# ==============================================================

cat > "$ROOT/grantbot/discovery/stats.py" <<'PY'
from __future__ import annotations

from grantbot.core.database import (
    fetch_all,
    fetch_one,
)


def discovery_stats() -> dict:

    opportunity_count = fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM opportunities
        """
    )["n"]

    source_counts = fetch_all(
        """
        SELECT
            COALESCE(
                p.source_key,
                'unknown'
            ) AS source_key,

            COUNT(o.id) AS opportunities

        FROM opportunities o

        LEFT JOIN funding_source_profiles p
          ON p.source_id=o.funding_source_id

        GROUP BY
            p.source_key

        ORDER BY
            opportunities DESC
        """
    )

    run_count = fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM discovery_runs
        """
    )["n"]

    latest_runs = fetch_all(
        """
        SELECT *
        FROM discovery_runs
        ORDER BY id DESC
        LIMIT 10
        """
    )

    page_count = fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM discovery_source_pages
        WHERE active=1
        """
    )["n"]

    return {
        "opportunities":
            opportunity_count,

        "registered_live_pages":
            page_count,

        "discovery_runs":
            run_count,

        "by_source":
            source_counts,

        "latest_runs":
            latest_runs,
    }
PY

# ==============================================================
# CLI
# ==============================================================

cat > "$ROOT/grantbot/discovery/cli.py" <<'PY'
from __future__ import annotations

import argparse
import json

from grantbot.core.database import (
    initialize_database,
)

from grantbot.discovery.brave import (
    BraveSearchProvider,
)

from grantbot.discovery.cache import (
    FileCache,
)

from grantbot.discovery.engine import (
    DiscoveryEngine,
)

from grantbot.discovery.pages import (
    add_page,
    list_pages,
    remove_page,
)

from grantbot.discovery.runner import (
    run_discovery_plan,
)

from grantbot.discovery.schema import (
    initialize_discovery_schema,
)

from grantbot.discovery.stats import (
    discovery_stats,
)

from grantbot.funding.registry import (
    seed_catalog,
)

from grantbot.funding.schema import (
    initialize_funding_schema,
)


def pretty(value):

    print(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


def build_parser():

    parser = argparse.ArgumentParser(
        prog="grantbot-discovery",

        description=(
            "GrantBot Pro live funding "
            "discovery engine"
        ),
    )

    sub = parser.add_subparsers(
        dest="command"
    )

    grants = sub.add_parser(
        "grants-gov",
        help=(
            "Search live Grants.gov "
            "opportunities."
        ),
    )

    grants.add_argument(
        "query"
    )

    grants.add_argument(
        "--limit",
        type=int,
        default=20,
    )

    grants.add_argument(
        "--details",
        type=int,
        default=5,
    )

    grants.add_argument(
        "--no-save",
        action="store_true",
    )

    grants.add_argument(
        "--lane",
        default=None,
    )


    page = sub.add_parser(
        "add-page",
        help=(
            "Register an official funding "
            "page or RSS feed."
        ),
    )

    page.add_argument(
        "--source-key",
        required=True,
    )

    page.add_argument(
        "--url",
        required=True,
    )

    page.add_argument(
        "--name",
        default=None,
    )

    page.add_argument(
        "--type",
        default="HTML",
        choices=[
            "HTML",
            "RSS",
            "JSON",
        ],
    )

    page.add_argument(
        "--max-links",
        type=int,
        default=100,
    )

    page.add_argument(
        "--ignore-robots",
        action="store_true",
    )


    pages = sub.add_parser(
        "pages",
        help=(
            "List registered live "
            "funding pages."
        ),
    )

    pages.add_argument(
        "--source-key",
        default=None,
    )


    remove = sub.add_parser(
        "remove-page",
        help=(
            "Remove a registered page."
        ),
    )

    remove.add_argument(
        "page_id",
        type=int,
    )


    crawl = sub.add_parser(
        "crawl",
        help=(
            "Search registered official "
            "pages for a source."
        ),
    )

    crawl.add_argument(
        "--source-key",
        required=True,
    )

    crawl.add_argument(
        "--query",
        required=True,
    )

    crawl.add_argument(
        "--geography",
        default="Florida",
    )

    crawl.add_argument(
        "--limit",
        type=int,
        default=25,
    )

    crawl.add_argument(
        "--lane",
        default=None,
    )

    crawl.add_argument(
        "--no-save",
        action="store_true",
    )


    web = sub.add_parser(
        "web-search",
        help=(
            "Run an optional Brave "
            "Search discovery query."
        ),
    )

    web.add_argument(
        "query"
    )

    web.add_argument(
        "--count",
        type=int,
        default=10,
    )


    plan = sub.add_parser(
        "run-plan",
        help=(
            "Execute Module 03's universal "
            "funding discovery plan."
        ),
    )

    plan.add_argument(
        "--state",
        default="Florida",
    )

    plan.add_argument(
        "--county",
        action="append",
        default=[],
    )

    plan.add_argument(
        "--city",
        action="append",
        default=[],
    )

    plan.add_argument(
        "--lane",
        action="append",
        default=[],
    )

    plan.add_argument(
        "--max-queries",
        type=int,
        default=20,
    )

    plan.add_argument(
        "--per-query",
        type=int,
        default=10,
    )

    plan.add_argument(
        "--web",
        action="store_true",
    )

    plan.add_argument(
        "--no-save",
        action="store_true",
    )


    live = sub.add_parser(
        "live-test",
        help=(
            "Verify live Grants.gov "
            "connectivity."
        ),
    )

    live.add_argument(
        "--query",
        default="reentry",
    )


    sub.add_parser(
        "stats",
        help=(
            "Show discovery statistics."
        ),
    )


    sub.add_parser(
        "clear-cache",
        help=(
            "Clear HTTP discovery cache."
        ),
    )

    return parser


def initialize():

    initialize_database()

    initialize_funding_schema()

    initialize_discovery_schema()

    seed_catalog()


def main():

    initialize()

    parser = build_parser()

    args = parser.parse_args()

    if args.command == "grants-gov":

        engine = DiscoveryEngine()

        pretty(
            engine.grants_gov(
                query=args.query,
                limit=args.limit,
                detail_limit=args.details,
                save=(
                    not args.no_save
                ),
                lane=args.lane,
            )
        )

        return


    if args.command == "add-page":

        pretty(
            add_page(
                source_key=(
                    args.source_key
                ),
                url=args.url,
                page_name=args.name,
                page_type=args.type,
                respect_robots=(
                    not args.ignore_robots
                ),
                max_links=(
                    args.max_links
                ),
            )
        )

        return


    if args.command == "pages":

        pretty(
            list_pages(
                args.source_key
            )
        )

        return


    if args.command == "remove-page":

        print(
            "REMOVED"
            if remove_page(
                args.page_id
            )
            else "NOT FOUND"
        )

        return


    if args.command == "crawl":

        engine = DiscoveryEngine()

        pretty(
            engine.crawl_registered_pages(
                source_key=(
                    args.source_key
                ),
                query=args.query,
                geography=(
                    args.geography
                ),
                limit=args.limit,
                save=(
                    not args.no_save
                ),
                lane=args.lane,
            )
        )

        return


    if args.command == "web-search":

        provider = (
            BraveSearchProvider()
        )

        pretty(
            provider.search(
                args.query,
                count=args.count,
            )
        )

        return


    if args.command == "run-plan":

        pretty(
            run_discovery_plan(
                state=args.state,
                counties=args.county,
                cities=args.city,
                lanes=(
                    args.lane
                    or None
                ),
                max_queries=(
                    args.max_queries
                ),
                per_query_limit=(
                    args.per_query
                ),
                use_web=args.web,
                save=(
                    not args.no_save
                ),
            )
        )

        return


    if args.command == "live-test":

        engine = DiscoveryEngine()

        result = (
            engine.grants_gov(
                query=args.query,
                limit=3,
                detail_limit=1,
                save=False,
            )
        )

        print(
            "GRANTS.GOV LIVE: OK"
        )

        pretty({
            "results_seen":
                result[
                    "seen"
                ],

            "sample":
                result[
                    "results"
                ][:3],
        })

        return


    if args.command == "stats":

        pretty(
            discovery_stats()
        )

        return


    if args.command == "clear-cache":

        count = (
            FileCache().clear()
        )

        print(
            f"Cleared {count} "
            f"cached HTTP responses."
        )

        return


    parser.print_help()


if __name__ == "__main__":
    main()
PY

# ==============================================================
# TESTS — NO INTERNET REQUIRED
# ==============================================================

cat > "$ROOT/tests/test_discovery.py" <<'PY'
from grantbot.core.database import (
    initialize_database,
)

from grantbot.discovery.dedupe import (
    fingerprint,
)

from grantbot.discovery.extract import (
    extract_award_range,
    extract_deadline,
    funding_relevance,
)

from grantbot.discovery.pages import (
    add_page,
    list_pages,
)

from grantbot.discovery.query_builder import (
    build_web_query,
)

from grantbot.discovery.schema import (
    initialize_discovery_schema,
)

from grantbot.funding.connectors.grants_gov import (
    ATTRIBUTION,
    GrantsGovAdapter,
)

from grantbot.funding.adapters import (
    SearchRequest,
)

from grantbot.funding.registry import (
    seed_catalog,
)

from grantbot.funding.schema import (
    initialize_funding_schema,
)


class FakeClient:

    user_agent = (
        "GrantBotPro-Test"
    )

    def post_json(
        self,
        url,
        *,
        json_body,
        **kwargs,
    ):

        if url.endswith(
            "/search2"
        ):

            return {
                "errorcode": 0,

                "msg":
                    "Webservice Succeeds",

                "data": {
                    "hitCount": 1,

                    "oppHits": [{
                        "id":
                            "289999",

                        "number":
                            "TEST-001",

                        "title":
                            "Reentry Workforce Housing Grant",

                        "agencyCode":
                            "TEST",

                        "agencyName":
                            "Test Agency",

                        "openDate":
                            "01/01/2026",

                        "closeDate":
                            "12/31/2026",

                        "oppStatus":
                            "posted",

                        "alnist":
                            [
                                "00.000"
                            ],
                    }],
                },
            }

        if url.endswith(
            "/fetchOpportunity"
        ):

            return {
                "errorcode": 0,

                "data": {
                    "id":
                        289999,

                    "opportunityTitle":
                        "Reentry Workforce Housing Grant",

                    "synopsis": {
                        "agencyName":
                            "Test Agency",

                        "synopsisDesc":
                            (
                                "Funds workforce, "
                                "housing, and reentry."
                            ),

                        "awardFloor":
                            "50000",

                        "awardCeiling":
                            "250000",

                        "applicantTypes": [{
                            "id":
                                "12",

                            "description":
                                (
                                    "Nonprofits having "
                                    "a 501(c)(3) status"
                                ),
                        }],
                    },
                },
            }

        raise AssertionError(
            f"Unexpected URL: {url}"
        )


def setup_module():

    initialize_database()

    initialize_funding_schema()

    initialize_discovery_schema()

    seed_catalog()


def test_grants_gov_normalization():

    adapter = GrantsGovAdapter(
        client=FakeClient(),
        enrich_details=True,
        detail_limit=1,
    )

    results = list(
        adapter.search(
            SearchRequest(
                query="reentry",
                limit=5,
            )
        )
    )

    assert len(
        results
    ) == 1

    result = results[0]

    assert (
        result.external_id
        == "289999"
    )

    assert (
        result.award_floor
        == 50000
    )

    assert (
        result.award_ceiling
        == 250000
    )

    assert (
        "501(c)(3)"
        in result.eligibility
    )


def test_grants_gov_attribution():

    assert (
        "not endorsed"
        in ATTRIBUTION
    )


def test_relevance():

    score = funding_relevance(
        (
            "Notice of Funding Opportunity "
            "for nonprofit reentry housing "
            "and workforce development"
        ),
        "reentry housing",
    )

    assert score >= 10


def test_deadline():

    deadline = extract_deadline(
        (
            "Applications are accepted now. "
            "Application deadline: "
            "December 15, 2026."
        )
    )

    assert (
        deadline
        == "December 15, 2026"
    )


def test_award_range():

    low, high = (
        extract_award_range(
            (
                "Awards range from "
                "$25,000 to $100,000."
            )
        )
    )

    assert low == 25000

    assert high == 100000


def test_fingerprint_stable():

    one = fingerprint(
        source_key="test",
        title="Grant A",
        source_url=(
            "https://example.org/a"
        ),
    )

    two = fingerprint(
        source_key="test",
        title="Grant A",
        source_url=(
            "https://example.org/a"
        ),
    )

    assert one == two


def test_page_registration():

    page = add_page(
        source_key=(
            "community_foundations"
        ),
        url=(
            "https://example.org/"
            "funding-opportunities"
        ),
        page_name=(
            "Test Funding Page"
        ),
        page_type="HTML",
    )

    assert (
        page["source_key"]
        == "community_foundations"
    )

    pages = list_pages(
        "community_foundations"
    )

    assert any(
        row["url"]
        == (
            "https://example.org/"
            "funding-opportunities"
        )
        for row in pages
    )


def test_government_web_query():

    query = build_web_query({
        "query":
            "reentry Sarasota County Florida",

        "lane":
            "reentry",

        "source_kind":
            "GOVERNMENT",

        "jurisdiction":
            "COUNTY",
    })

    assert (
        "site:.gov"
        in query
    )

    assert (
        "reentry"
        in query
    )
PY

# ==============================================================
# COMPILE
# ==============================================================

cd "$ROOT"

echo
echo "=== Compiling Module 04 ==="

"$PYTHON" \
    -m compileall \
    -q \
    grantbot/discovery \
    grantbot/funding/connectors \
    tests/test_discovery.py

# ==============================================================
# INITIALIZE
# ==============================================================

echo
echo "=== Initializing live discovery schema ==="

PYTHONPATH="$ROOT" \
"$PYTHON" - <<'PY'
from grantbot.core.database import initialize_database
from grantbot.funding.schema import initialize_funding_schema
from grantbot.funding.registry import seed_catalog
from grantbot.discovery.schema import initialize_discovery_schema

initialize_database()
initialize_funding_schema()
initialize_discovery_schema()
seed_catalog()

print("Live discovery database ready.")
PY

# ==============================================================
# POINT GRANTS.GOV REGISTRY TO CURRENT API
# ==============================================================

PYTHONPATH="$ROOT" \
"$PYTHON" - <<'PY'
from grantbot.core.database import connection, utc_now

with connection() as conn:
    row = conn.execute(
        """
        SELECT fs.id
        FROM funding_sources fs
        JOIN funding_source_profiles p
          ON p.source_id=fs.id
        WHERE p.source_key='federal_grants_gov'
        """
    ).fetchone()

    if row:
        conn.execute(
            """
            UPDATE funding_sources
            SET
                api_endpoint=?,
                website=?,
                updated_at=?
            WHERE id=?
            """,
            (
                "https://api.grants.gov/v1/api/search2",
                "https://www.grants.gov",
                utc_now(),
                row["id"],
            ),
        )

print("Grants.gov live endpoint configured.")
PY

# ==============================================================
# RUN UNIT TESTS
# ==============================================================

echo
echo "=== Running Module 04 tests ==="

PYTHONPATH="$ROOT" \
"$PYTHON" \
    -m pytest \
    tests/test_discovery.py \
    -q

# ==============================================================
# PRINT STATUS
# ==============================================================

echo
echo "=== Discovery engine status ==="

PYTHONPATH="$ROOT" \
"$PYTHON" \
    -m grantbot.discovery.cli \
    stats

echo
echo "================================================================"
echo " MODULE 04 INSTALLED SUCCESSFULLY"
echo "================================================================"
echo
echo "LIVE CAPABILITIES:"
echo
echo "  ✓ Grants.gov search2"
echo "  ✓ Grants.gov fetchOpportunity"
echo "  ✓ Federal detail enrichment"
echo "  ✓ Applicant eligibility extraction"
echo "  ✓ Award floor / ceiling ingestion"
echo "  ✓ Deadline ingestion"
echo "  ✓ Official government-page crawler"
echo "  ✓ Foundation funding-page crawler"
echo "  ✓ Corporate funding-page crawler"
echo "  ✓ Faith-based funding-page crawler"
echo "  ✓ County funding-page crawler"
echo "  ✓ City funding-page crawler"
echo "  ✓ CRA funding-page crawler"
echo "  ✓ CDFI funding-page crawler"
echo "  ✓ RSS funding feeds"
echo "  ✓ robots.txt compliance"
echo "  ✓ HTTP retries / exponential backoff"
echo "  ✓ Rate limiting"
echo "  ✓ Local request cache"
echo "  ✓ Response-size protection"
echo "  ✓ Opportunity deduplication"
echo "  ✓ Stable opportunity fingerprints"
echo "  ✓ Discovery-run audit history"
echo "  ✓ Funding relevance analysis"
echo "  ✓ Deadline extraction"
echo "  ✓ Award-range extraction"
echo "  ✓ Eligibility-snippet extraction"
echo "  ✓ Mission-keyword detection"
echo "  ✓ Module 03 discovery-plan execution"
echo "  ✓ Optional Brave Search discovery"
echo "  ✓ Angel / impact-investor web discovery"
echo
echo "GRANTS.GOV REQUIRES NO API KEY."
echo
echo "Test it live with:"
echo
echo "cd ~/grantbot_pro"
echo
echo ".venv/bin/python -m grantbot.discovery.cli live-test --query 'reentry housing workforce'"
echo
echo "Search and SAVE real federal opportunities:"
echo
echo ".venv/bin/python -m grantbot.discovery.cli grants-gov 'reentry housing workforce' --limit 25 --details 10 --lane reentry"
echo
echo "See what was saved:"
echo
echo ".venv/bin/python -m grantbot.discovery.cli stats"
echo
echo "REGISTER A CITY/COUNTY/FOUNDATION FUNDING PAGE:"
echo
echo ".venv/bin/python -m grantbot.discovery.cli add-page \\"
echo "  --source-key florida_counties \\"
echo "  --url 'PASTE_OFFICIAL_FUNDING_PAGE_URL' \\"
echo "  --name 'County Funding'"
echo
echo "Then search that official page:"
echo
echo ".venv/bin/python -m grantbot.discovery.cli crawl \\"
echo "  --source-key florida_counties \\"
echo "  --query 'housing reentry workforce' \\"
echo "  --geography 'Florida'"
echo
echo "OPTIONAL BROAD WEB DISCOVERY:"
echo
echo "Add your Brave Search API key to:"
echo "  ~/grantbot_pro/.env"
echo
echo "Then set:"
echo "  GRANTBOT_BRAVE_ENABLED=1"
echo "  BRAVE_SEARCH_API_KEY=YOUR_KEY"
echo
echo "Then Module 03's entire universal discovery plan can use"
echo "live web search for city, county, state, foundation,"
echo "corporate, faith-based, angel, and impact-capital sources."
echo
echo "NEXT MODULE:"
echo
echo "MODULE 05 — NOFO / PDF / DOCX INTELLIGENCE ENGINE"
echo
echo "That module will download and understand the FULL grant"
echo "announcement, not just the listing:"
echo
echo "  eligibility"
echo "  deadlines"
echo "  scoring criteria"
echo "  required attachments"
echo "  match requirements"
echo "  allowable costs"
echo "  prohibited costs"
echo "  page/word limits"
echo "  certifications"
echo "  application questions"
echo "  submission rules"
echo "  contacts"
echo "  compliance requirements"
echo
