from __future__ import annotations

import html
import json
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from grantbot.discovery.grants_gov import fetch_opportunity
from grantbot.nofo.full_detail import get_full_nofo_intelligence


MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024
TIMEOUT_SECONDS = 30
ALLOWED_HOST_SUFFIXES = (".gov", "grants.gov", "simpler.grants.gov")

QUESTION_RE = re.compile(
    r"\b(describe|explain|provide|discuss|identify|demonstrate|summarize|"
    r"detail|outline|justify|address|state|specify|document)\b",
    re.I,
)

REQUIREMENT_RE = re.compile(
    r"\b(must|shall|required|submit|attach|attachment|budget|narrative|"
    r"timeline|work plan|logic model|letter|MOU|MOA|SF-424|UEI|SAM\.gov|"
    r"match|cost[- ]sharing|performance measure|data collection)\b",
    re.I,
)

SCORING_RE = re.compile(
    r"\b(points?|percent|percentage|weighted|weight)\b|\b\d{1,3}\s*%",
    re.I,
)

BUDGET_RE = re.compile(
    r"\b(budget|budget narrative|allowable cost|indirect cost|personnel|"
    r"fringe|travel|equipment|supplies|contractual|construction|other costs?)\b",
    re.I,
)

MATCH_RE = re.compile(
    r"\b(match|matching funds?|cost[- ]sharing|non[- ]federal share|"
    r"in[- ]kind|cash contribution|waiver)\b",
    re.I,
)

SUBMISSION_RE = re.compile(
    r"\b(submit|submission|Grants\.gov|JustGrants|deadline|due date|"
    r"SAM\.gov|UEI|registration|application package)\b",
    re.I,
)

ATTACHMENT_RE = re.compile(
    r"\b(attachment|appendix|letter of support|letter of commitment|"
    r"memorandum of understanding|memorandum of agreement|MOU|MOA|"
    r"logic model|timeline|work plan|budget narrative|project narrative|"
    r"organizational chart|indirect cost rate agreement)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class ApplicationBlueprint:
    opportunity_id: str
    opportunity_number: str
    title: str
    funder: str
    acquisition_status: str
    source_urls: list[str]
    application_questions: list[str]
    requirements: list[str]
    scoring_criteria: list[str]
    budget_requirements: list[str]
    match_requirements: list[str]
    submission_requirements: list[str]
    required_attachments: list[str]
    eligibility: list[str]
    award_ceiling: float | None
    award_floor: float | None
    cost_sharing: bool | None
    warnings: list[str]
    output_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self._ignore = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript", "svg"}:
            self._ignore += 1
        if low == "a":
            for key, value in attrs:
                if key.lower() == "href" and value:
                    self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._ignore:
            self._ignore -= 1

    def handle_data(self, data: str) -> None:
        if self._ignore:
            return
        value = " ".join(data.split()).strip()
        if value:
            self.parts.append(value)


def _safe_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False

    if parsed.scheme != "https":
        return False

    host = (parsed.hostname or "").lower()
    return any(
        host == suffix.lstrip(".") or host.endswith(suffix)
        for suffix in ALLOWED_HOST_SUFFIXES
    )


def _dedupe(values: list[str], limit: int = 300) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for raw in values:
        value = " ".join(str(raw).split()).strip()
        key = value.casefold()

        if not value or key in seen:
            continue

        seen.add(key)
        result.append(value)

        if len(result) >= limit:
            break

    return result


def _walk_strings(value: Any) -> list[str]:
    result: list[str] = []

    if isinstance(value, str):
        result.append(value)
    elif isinstance(value, dict):
        for nested in value.values():
            result.extend(_walk_strings(nested))
    elif isinstance(value, list):
        for nested in value:
            result.extend(_walk_strings(nested))

    return result


def _request(url: str) -> tuple[bytes, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "GrantBotPro/13.0",
            "Accept": "application/pdf,text/html,text/plain,*/*;q=0.2",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    ) as response:
        final_url = response.geturl()

        if not _safe_url(final_url):
            raise ValueError(f"Unsafe redirect: {final_url}")

        content_type = response.headers.get_content_type() or "application/octet-stream"
        data = response.read(MAX_DOWNLOAD_BYTES + 1)

        if len(data) > MAX_DOWNLOAD_BYTES:
            raise ValueError("NOFO document exceeds download size limit")

        return data, content_type, final_url


def _extract_text(
    data: bytes,
    content_type: str,
    url: str,
) -> tuple[str, list[str]]:
    path = urllib.parse.urlparse(url).path.lower()

    if content_type == "application/pdf" or path.endswith(".pdf"):
        reader = PdfReader(BytesIO(data))
        parts: list[str] = []

        for page in reader.pages:
            value = page.extract_text() or ""
            if value.strip():
                parts.append(value)

        return "\n".join(parts), []

    if content_type == "text/html" or path.endswith((".html", ".htm")):
        parser = _HTMLTextParser()
        parser.feed(data.decode("utf-8", errors="replace"))

        links = [
            urllib.parse.urljoin(url, href)
            for href in parser.links
        ]

        return "\n".join(parser.parts), links

    if content_type.startswith("text/") or path.endswith(".txt"):
        return data.decode("utf-8", errors="replace"), []

    return "", []


def _lines(text: str) -> list[str]:
    result: list[str] = []

    for raw in text.replace("\r", "\n").split("\n"):
        value = " ".join(raw.split()).strip()
        if 10 <= len(value) <= 1200:
            result.append(value)

    return result


def _matching(
    lines: list[str],
    pattern: re.Pattern[str],
    limit: int,
) -> list[str]:
    return _dedupe(
        [line for line in lines if pattern.search(line)],
        limit=limit,
    )



def _validated_extract(lines: list[str], kind: str) -> list[str]:
    rules = {
        "question": (
            "describe", "explain", "provide", "identify", "demonstrate",
            "discuss", "summarize", "how will", "what is", "what are",
            "applicant", "project", "program", "organization",
        ),
        "requirement": (
            "must ", "shall ", "required", "requirement",
            "applicant", "recipient", "eligible", "eligibility",
        ),
        "scoring": (
            "scoring", "evaluation criteria", "rating factor",
            "selection criteria", "maximum points", "review criteria",
        ),
        "budget": (
            "budget", "allowable cost", "eligible cost", "indirect cost",
            "construction", "rehabilitation", "acquisition",
            "rental assistance",
        ),
        "match": (
            "matching funds", "match requirement", "cost sharing",
            "cost-sharing", "non-federal share", "in-kind match",
        ),
        "submission": (
            "submit the application", "application must be submitted",
            "submission deadline", "application deadline", "due date",
            "grants.gov", "application package", "electronic submission",
        ),
        "attachment": (
            "required attachment", "attachment ", "sf-424", "sf424",
            "budget narrative", "budget worksheet", "letter of commitment",
            "letter of support", "organizational chart", "logic model",
            "resume", "certification", "assurances", "agreement",
        ),
    }

    noise = (
        "questions or comments",
        "can you talk about",
        "did you read",
        "do you know",
        "how did you",
        "who else",
        "office hours",
        "find state resources",
        "balance of state coc",
        "submit questions",
        "comments or questions",
        "aaq desk",
    )

    result = []

    for raw in lines:
        text = " ".join(str(raw).split()).strip()
        low = text.lower()

        if len(text) < 8 or len(text) > 700:
            continue

        if any(x in low for x in noise):
            continue

        if kind == "question":
            if "?" not in text and not any(
                low.startswith(x)
                for x in (
                    "describe ",
                    "explain ",
                    "provide ",
                    "identify ",
                    "demonstrate ",
                    "discuss ",
                    "summarize ",
                )
            ):
                continue

        if kind == "attachment" and len(text) > 300:
            continue

        if any(x in low for x in rules[kind]):
            result.append(text)

    return _dedupe(result, limit=250)


def acquire_blueprint(
    opportunity_id: str,
    *,
    manual_urls: list[str] | None = None,
) -> ApplicationBlueprint:
    opportunity_id = opportunity_id.strip()

    if not opportunity_id or len(opportunity_id) > 80:
        raise ValueError("Invalid opportunity_id")

    raw = fetch_opportunity(opportunity_id)

    if not isinstance(raw, dict):
        raise RuntimeError("Invalid Grants.gov opportunity payload")

    full = get_full_nofo_intelligence(opportunity_id)

    urls = [
        f"https://www.grants.gov/search-results-detail/"
        f"{urllib.parse.quote(opportunity_id, safe='')}"
    ]

    for value in _walk_strings(raw):
        value = html.unescape(value.strip())
        if value.startswith("https://") and _safe_url(value):
            urls.append(value)

    for value in manual_urls or []:
        value = value.strip()
        if not _safe_url(value):
            raise ValueError(
                f"Manual NOFO URL must be an HTTPS government source: {value}"
            )
        urls.append(value)

    queue = _dedupe(urls, limit=60)
    visited: set[str] = set()
    acquired_urls: list[str] = []
    text_parts: list[str] = []
    warnings: list[str] = []

    while queue and len(visited) < 40:
        url = queue.pop(0)

        if url in visited or not _safe_url(url):
            continue

        visited.add(url)

        try:
            data, content_type, final_url = _request(url)
            text, links = _extract_text(data, content_type, final_url)

            if text.strip():
                text_parts.append(text)
                acquired_urls.append(final_url)

            for link in links:
                low = link.lower()

                if (
                    _safe_url(link)
                    and any(
                        token in low
                        for token in (
                            ".pdf",
                            "nofo",
                            "notice",
                            "attachment",
                            "download",
                            "instructions",
                        )
                    )
                    and link not in visited
                    and link not in queue
                ):
                    queue.append(link)

        except Exception as exc:
            warnings.append(
                f"{url}: {type(exc).__name__}: {exc}"
            )

    combined = "\n\n".join(text_parts)[:2_000_000]
    lines = _lines(combined)

    questions = _validated_extract(lines, "question")
    requirements = _validated_extract(lines, "requirement")
    scoring_criteria = _validated_extract(lines, "scoring")
    budget_requirements = _validated_extract(lines, "budget")
    match_requirements = _validated_extract(lines, "match")
    submission_requirements = _validated_extract(lines, "submission")
    required_attachments = _validated_extract(lines, "attachment")

    quality_count = sum(
        bool(x)
        for x in (
            questions,
            requirements,
            scoring_criteria,
            budget_requirements,
            submission_requirements,
            required_attachments,
            full.eligibility,
        )
    )

    if not combined.strip():
        acquisition_status = "METADATA_ONLY"
    elif (
        quality_count >= 5
        and requirements
        and full.eligibility
        and (questions or submission_requirements)
    ):
        acquisition_status = "FULL_NOFO_VALIDATED"
    else:
        acquisition_status = "FULL_TEXT_ACQUIRED"

    if not questions:
        warnings.append(
            "No application questions were extracted from acquired source text."
        )

    root = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "nofo_blueprints"
        / re.sub(r"[^A-Za-z0-9._-]+", "_", opportunity_id)
    )
    root.mkdir(parents=True, exist_ok=True)

    output_path = root / "application_blueprint.json"

    blueprint = ApplicationBlueprint(
        opportunity_id=opportunity_id,
        opportunity_number=full.opportunity_number,
        title=full.title,
        funder=full.funder,
        acquisition_status=acquisition_status,
        source_urls=_dedupe(acquired_urls),
        application_questions=questions,
        requirements=requirements,
        scoring_criteria=scoring_criteria,
        budget_requirements=budget_requirements,
        match_requirements=match_requirements,
        submission_requirements=submission_requirements,
        required_attachments=required_attachments,
        eligibility=full.eligibility,
        award_ceiling=full.award_ceiling,
        award_floor=full.award_floor,
        cost_sharing=full.cost_sharing,
        warnings=_dedupe(warnings, limit=100),
        output_path=str(output_path),
    )

    output_path.write_text(
        json.dumps(
            blueprint.to_dict(),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    return blueprint


def load_blueprint(opportunity_id: str) -> dict[str, Any]:
    safe_id = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        opportunity_id.strip(),
    )

    path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "nofo_blueprints"
        / safe_id
        / "application_blueprint.json"
    )

    if not path.exists():
        raise FileNotFoundError(str(path))

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise RuntimeError("Stored NOFO blueprint is invalid")

    return data
