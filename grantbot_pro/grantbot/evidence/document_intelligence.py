from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any


AUTHORITY_RANKS = {
    "PRIMARY_NOFO": 1,
    "AMENDMENT": 2,
    "APPLICATION_INSTRUCTIONS": 3,
    "OFFICIAL_FORM": 4,
    "OFFICIAL_FAQ": 5,
    "OFFICIAL_GUIDANCE": 6,
    "WEBINAR_TRANSCRIPT": 7,
    "INFORMATIONAL_WEBPAGE": 8,
    "OTHER": 9,
}

MANDATORY_RE = re.compile(r"\b(must|shall|required|is required to|are required to)\b", re.I)
CONDITIONAL_RE = re.compile(r"\b(if|when|where applicable|as applicable|unless|for applicants that)\b", re.I)
CATEGORY_RULES = (
    ("ELIGIBILITY", re.compile(r"\b(eligible|eligibility|applicant type|nonprofit|501\(c\)\(3\)|government|tribal|institution)\b", re.I)),
    ("MATCH", re.compile(r"\b(match|matching|cost[- ]sharing|non[- ]federal share|in[- ]kind)\b", re.I)),
    ("BUDGET", re.compile(r"\b(budget|allowable cost|unallowable cost|indirect cost|personnel|fringe|equipment|construction)\b", re.I)),
    ("ATTACHMENT", re.compile(r"\b(attachment|appendix|letter of support|letter of commitment|MOU|MOA|logic model|work plan|budget narrative)\b", re.I)),
    ("SUBMISSION", re.compile(r"\b(submit|submission|deadline|due date|grants\.gov|sam\.gov|uei|signature|file format)\b", re.I)),
    ("SCORING", re.compile(r"\b(points?|scoring|selection criteria|review criteria|rating factor|weighted|percentage)\b", re.I)),
    ("REPORTING", re.compile(r"\b(reporting|performance measure|data collection|quarterly report|annual report)\b", re.I)),
    ("COMPLIANCE", re.compile(r"\b(procurement|environmental review|Davis-Bacon|audit|certification|assurance|2 CFR|uniform guidance)\b", re.I)),
)


@dataclass(frozen=True, slots=True)
class RequirementEvidence:
    requirement_id: str
    category: str
    requirement_level: str
    text: str
    page_number: int
    section: str
    authority_type: str
    authority_rank: int
    source_url: str
    document_title: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_authority(
    *,
    source_url: str = "",
    title: str = "",
    document_type: str = "",
) -> str:
    text = f"{source_url} {title} {document_type}".lower()
    if "amendment" in text:
        return "AMENDMENT"
    if any(term in text for term in ("notice of funding opportunity", "nofo", "funding opportunity announcement", "foa")):
        return "PRIMARY_NOFO"
    if any(term in text for term in ("application instruction", "application guide", "application package instruction")):
        return "APPLICATION_INSTRUCTIONS"
    if any(term in text for term in ("sf-424", "sf424", "official form", "form ")):
        return "OFFICIAL_FORM"
    if any(term in text for term in ("faq", "frequently asked")):
        return "OFFICIAL_FAQ"
    if any(term in text for term in ("webinar", "transcript", "office hours")):
        return "WEBINAR_TRANSCRIPT"
    if any(term in text for term in ("guidance", "guidebook", "policy guide")):
        return "OFFICIAL_GUIDANCE"
    if source_url:
        return "INFORMATIONAL_WEBPAGE"
    return "OTHER"


def _section_hint(text: str) -> str:
    clean = " ".join(text.split())
    match = re.match(r"^(?:section\s+)?([A-Z0-9IVX.-]{1,12})\s*[:.-]\s*(.{3,100})$", clean, re.I)
    if match:
        return clean[:120]
    return ""


def _category(text: str) -> str:
    for category, pattern in CATEGORY_RULES:
        if pattern.search(text):
            return category
    return "GENERAL"


def _level(text: str) -> str:
    if MANDATORY_RE.search(text):
        return "MANDATORY"
    if CONDITIONAL_RE.search(text):
        return "CONDITIONAL"
    return "OPTIONAL"


def _confidence(text: str, authority_rank: int, category: str) -> float:
    score = 0.62
    if MANDATORY_RE.search(text):
        score += 0.14
    if category != "GENERAL":
        score += 0.08
    if authority_rank <= 3:
        score += 0.10
    elif authority_rank >= 7:
        score -= 0.10
    if len(text) >= 40:
        score += 0.04
    return round(max(0.0, min(score, 0.99)), 2)


def _candidate_lines(page: str) -> list[str]:
    lines: list[str] = []
    for raw in page.replace("\r", "\n").split("\n"):
        text = " ".join(raw.split()).strip()
        if 12 <= len(text) <= 1200:
            lines.append(text)
    return lines


def extract_requirements(
    *,
    opportunity_id: str,
    pages: list[str],
    source_url: str = "",
    title: str = "",
    document_type: str = "",
    authority_type: str = "AUTO",
) -> list[dict[str, Any]]:
    resolved_authority = (
        classify_authority(source_url=source_url, title=title, document_type=document_type)
        if authority_type.upper() == "AUTO"
        else authority_type.upper()
    )
    if resolved_authority not in AUTHORITY_RANKS:
        raise ValueError(f"Unknown authority_type: {resolved_authority}")
    rank = AUTHORITY_RANKS[resolved_authority]
    results: list[RequirementEvidence] = []
    seen: set[str] = set()
    section = ""
    for page_number, page in enumerate(pages, start=1):
        for line in _candidate_lines(page):
            hint = _section_hint(line)
            if hint:
                section = hint
            category = _category(line)
            level = _level(line)
            is_requirement = (
                level != "OPTIONAL"
                or category in {"ELIGIBILITY", "MATCH", "ATTACHMENT", "SUBMISSION", "SCORING", "COMPLIANCE"}
            )
            if not is_requirement:
                continue
            normalized = line.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            digest = hashlib.sha256(
                f"{opportunity_id}\x1f{source_url}\x1f{page_number}\x1f{line}".encode("utf-8")
            ).hexdigest()[:24]
            results.append(
                RequirementEvidence(
                    requirement_id=f"req_{digest}",
                    category=category,
                    requirement_level=level,
                    text=line,
                    page_number=page_number,
                    section=section,
                    authority_type=resolved_authority,
                    authority_rank=rank,
                    source_url=source_url,
                    document_title=title,
                    confidence=_confidence(line, rank, category),
                )
            )
    return [item.to_dict() for item in results]


def authoritative_requirements(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not requirements:
        return []
    authoritative = [
        item
        for item in requirements
        if int(item.get("authority_rank", 9)) <= 6
    ]
    source = authoritative or requirements
    return sorted(
        source,
        key=lambda item: (
            int(item.get("authority_rank", 9)),
            int(item.get("page_number", 0)),
            str(item.get("text", "")),
        ),
    )
