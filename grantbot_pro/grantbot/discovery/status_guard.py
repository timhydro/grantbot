from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUTHORITY_REGISTRY = (
    PROJECT_ROOT / "data" / "discovery" / "authority_sources.json"
)
USER_AGENT = (
    "BrokenGrowthMinistries-GrantBot/27.1 "
    "(official-funding-status-verification)"
)
MAX_STATUS_BYTES = 2 * 1024 * 1024

INVALIDATING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("VACATED", re.compile(r"\bvacat(?:e|ed|es|ing)\b", re.I)),
    ("RESCINDED", re.compile(r"\brescind(?:ed|s|ing)?\b", re.I)),
    ("WITHDRAWN", re.compile(r"\bwithdrawn\b|\bwithdrawal\b", re.I)),
    ("CANCELLED", re.compile(r"\bcancell?ed\b|\bcancellation\b", re.I)),
    ("TERMINATED", re.compile(r"\bterminated\b|\btermination\b", re.I)),
    ("SUPERSEDED", re.compile(r"\bsuperseded\b", re.I)),
    (
        "NO_LONGER_IN_FORCE",
        re.compile(r"\bno longer (?:in force|effective|valid|open)\b", re.I),
    ),
    (
        "UNABLE_TO_ACCEPT_APPLICATIONS",
        re.compile(r"\bunable to accept applications\b", re.I),
    ),
)

REVISION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("MODIFIED", re.compile(r"\bmodified\b", re.I)),
    ("AMENDED", re.compile(r"\bamended\b", re.I)),
    ("REVISED", re.compile(r"\brevised\b", re.I)),
)


class OpportunityState(str, Enum):
    ACTIVE = "ACTIVE"
    FORECASTED = "FORECASTED"
    CLOSED = "CLOSED"
    QUARANTINED = "QUARANTINED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True, slots=True)
class AuthoritySource:
    url: str
    match_terms: tuple[str, ...] = ()
    required: bool = False


@dataclass(frozen=True, slots=True)
class AuthorityCheck:
    url: str
    required: bool
    matched_terms: list[str]
    invalidating_flags: list[str]
    revision_flags: list[str]
    http_status: int | None
    error: str | None
    excerpt: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StatusDecision:
    state: str
    drafting_allowed: bool
    submission_allowed: bool
    reasons: list[str]
    checks: list[AuthorityCheck]

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "drafting_allowed": self.drafting_allowed,
            "submission_allowed": False,
            "reasons": list(self.reasons),
            "checks": [item.to_dict() for item in self.checks],
        }


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_deadline(value: str | None) -> date | None:
    raw = str(value or "").strip()

    if not raw:
        return None

    for fmt in (
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m-%d-%Y",
    ):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _is_official_gov_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme != "https":
        return False

    host = (parsed.hostname or "").lower().rstrip(".")
    return host == "gov" or host.endswith(".gov")


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return

    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_strings(child)
        return

    if isinstance(value, list):
        for child in value:
            yield from _iter_strings(child)


def _registry_sources(
    opportunity_number: str,
    registry_path: Path,
) -> list[AuthoritySource]:
    if not registry_path.is_file():
        return []

    try:
        root = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(root, dict):
        return []

    raw_items = root.get(opportunity_number, [])

    if not isinstance(raw_items, list):
        return []

    output: list[AuthoritySource] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        url = str(item.get("url", "")).strip()

        if not _is_official_gov_url(url):
            continue

        raw_terms = item.get("match_terms", [])
        terms = (
            tuple(
                _normalize_space(str(term))
                for term in raw_terms
                if _normalize_space(str(term))
            )
            if isinstance(raw_terms, list)
            else ()
        )

        output.append(
            AuthoritySource(
                url=url,
                match_terms=terms,
                required=bool(item.get("required", True)),
            )
        )

    return output


def _detail_sources(
    detail: dict[str, Any],
    *,
    opportunity_number: str,
    title: str,
    limit: int = 4,
) -> list[AuthoritySource]:
    urls: list[str] = []

    for raw in _iter_strings(detail):
        text = raw.strip()

        if not text.startswith("https://"):
            continue

        if not _is_official_gov_url(text):
            continue

        if text in urls:
            continue

        urls.append(text)

        if len(urls) >= limit:
            break

    terms = tuple(
        value
        for value in (
            opportunity_number.strip(),
            _normalize_space(title),
        )
        if value
    )

    return [
        AuthoritySource(
            url=url,
            match_terms=terms,
            required=False,
        )
        for url in urls
    ]


def _contexts_for_terms(
    text: str,
    match_terms: Iterable[str],
    *,
    radius: int = 1800,
) -> tuple[list[str], list[str]]:
    lowered = text.lower()
    contexts: list[str] = []
    matched_terms: list[str] = []

    for raw_term in match_terms:
        term = _normalize_space(str(raw_term))

        if not term:
            continue

        needle = term.lower()
        start_at = 0
        found_for_term = False

        while True:
            position = lowered.find(needle, start_at)

            if position < 0:
                break

            found_for_term = True
            start = max(0, position - radius)
            end = min(len(text), position + len(term) + radius)
            contexts.append(text[start:end])
            start_at = position + max(1, len(needle))

        if found_for_term:
            matched_terms.append(term)

    return contexts, matched_terms


def scan_authority_text(
    text: str,
    match_terms: Iterable[str],
) -> dict[str, Any]:
    clean = _normalize_space(text)
    contexts, matched_terms = _contexts_for_terms(clean, match_terms)

    invalidating: set[str] = set()
    revisions: set[str] = set()

    for context in contexts:
        for name, pattern in INVALIDATING_PATTERNS:
            if pattern.search(context):
                invalidating.add(name)

        for name, pattern in REVISION_PATTERNS:
            if pattern.search(context):
                revisions.add(name)

    return {
        "matched_terms": matched_terms,
        "invalidating_flags": sorted(invalidating),
        "revision_flags": sorted(revisions),
        "excerpt": contexts[0][:2500] if contexts else "",
    }


def _read_limited_response(response: requests.Response) -> str:
    chunks = bytearray()

    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue

        chunks.extend(chunk)

        if len(chunks) > MAX_STATUS_BYTES:
            raise RuntimeError(
                "Authority status page exceeded the 2 MiB safety limit."
            )

    return bytes(chunks).decode(
        response.encoding or "utf-8",
        errors="replace",
    )


def check_authority_source(
    source: AuthoritySource,
    *,
    session: requests.Session | None = None,
) -> AuthorityCheck:
    if not _is_official_gov_url(source.url):
        return AuthorityCheck(
            source.url,
            source.required,
            [],
            [],
            [],
            None,
            "Rejected non-.gov or non-HTTPS authority URL.",
            "",
        )

    client = session or requests.Session()

    try:
        response = client.get(
            source.url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,text/plain",
            },
            timeout=30,
            allow_redirects=True,
            stream=True,
        )
        response.raise_for_status()

        content_type = (
            response.headers.get("Content-Type", "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )

        if content_type not in {
            "",
            "text/html",
            "text/plain",
            "application/xhtml+xml",
        }:
            raise RuntimeError(
                "Authority URL did not return an HTML/text status page "
                f"(content-type={content_type or 'unknown'})."
            )

        raw = _read_limited_response(response)
        soup = BeautifulSoup(raw, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        scan = scan_authority_text(
            soup.get_text(" ", strip=True),
            source.match_terms,
        )

        return AuthorityCheck(
            source.url,
            source.required,
            scan["matched_terms"],
            scan["invalidating_flags"],
            scan["revision_flags"],
            response.status_code,
            None,
            scan["excerpt"],
        )

    except Exception as exc:
        return AuthorityCheck(
            source.url,
            source.required,
            [],
            [],
            [],
            None,
            f"{type(exc).__name__}: {exc}",
            "",
        )


def evaluate_opportunity_status(
    *,
    hit: dict[str, Any],
    detail: dict[str, Any] | None = None,
    verify_authority: bool = True,
    authority_registry_path: Path = DEFAULT_AUTHORITY_REGISTRY,
    today: date | None = None,
    session: requests.Session | None = None,
) -> StatusDecision:
    detail = detail or {}
    today_value = today or date.today()

    opportunity_number = str(
        detail.get("opportunityNumber")
        or hit.get("number")
        or ""
    ).strip()

    title = str(
        detail.get("opportunityTitle")
        or hit.get("title")
        or ""
    ).strip()

    status = str(hit.get("oppStatus") or "").strip().upper()
    synopsis = detail.get("synopsis") or {}
    close_date = parse_deadline(
        hit.get("closeDate")
        or synopsis.get("responseDateDesc")
    )

    reasons: list[str] = []

    if close_date is not None and close_date < today_value:
        return StatusDecision(
            OpportunityState.CLOSED.value,
            False,
            False,
            [f"Deadline passed on {close_date.isoformat()}."],
            [],
        )

    if status in {"CLOSED", "ARCHIVED"}:
        return StatusDecision(
            OpportunityState.CLOSED.value,
            False,
            False,
            [f"Grants.gov status is {status}."],
            [],
        )

    sources: list[AuthoritySource] = []

    if verify_authority and opportunity_number:
        sources.extend(
            _registry_sources(opportunity_number, authority_registry_path)
        )
        sources.extend(
            _detail_sources(
                detail,
                opportunity_number=opportunity_number,
                title=title,
            )
        )

    deduped: dict[str, AuthoritySource] = {}

    for source in sources:
        existing = deduped.get(source.url)

        if existing is None:
            deduped[source.url] = source
        else:
            deduped[source.url] = AuthoritySource(
                source.url,
                tuple(
                    dict.fromkeys(
                        [*existing.match_terms, *source.match_terms]
                    )
                ),
                existing.required or source.required,
            )

    checks = [
        check_authority_source(source, session=session)
        for source in deduped.values()
    ]

    invalidating = [
        item
        for item in checks
        if item.invalidating_flags
    ]

    if invalidating:
        for item in invalidating:
            reasons.append(
                "Official status source invalidated the opportunity: "
                + "/".join(item.invalidating_flags)
                + " — "
                + item.url
            )

        return StatusDecision(
            OpportunityState.QUARANTINED.value,
            False,
            False,
            reasons,
            checks,
        )

    required_failures = [
        item
        for item in checks
        if item.required and item.error
    ]

    if required_failures:
        reasons.extend(
            "Required authority check failed: "
            + item.url
            + " — "
            + str(item.error)
            for item in required_failures
        )

        return StatusDecision(
            OpportunityState.REVIEW_REQUIRED.value,
            False,
            False,
            reasons,
            checks,
        )

    if status == "FORECASTED":
        return StatusDecision(
            OpportunityState.FORECASTED.value,
            True,
            False,
            [
                "Opportunity is forecasted; planning/scoring is allowed, "
                "but it is not treated as open for submission."
            ],
            checks,
        )

    if status == "POSTED":
        return StatusDecision(
            OpportunityState.ACTIVE.value,
            True,
            False,
            [
                "Grants.gov status is POSTED and no official invalidation "
                "signal was detected."
            ],
            checks,
        )

    return StatusDecision(
        OpportunityState.REVIEW_REQUIRED.value,
        False,
        False,
        [
            f"Unrecognized or missing Grants.gov status: "
            f"{status or 'UNKNOWN'}."
        ],
        checks,
    )
