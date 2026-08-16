from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from grantbot.discovery.grants_gov import fetch_opportunity
from grantbot.nofo.analyzer import analyze_nofo


@dataclass(frozen=True, slots=True)
class Attachment:
    id: int | None
    file_name: str
    mime_type: str
    description: str
    size_bytes: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FullNofoResult:
    opportunity_id: str
    opportunity_number: str
    title: str
    funder: str
    eligibility: list[str]
    funding_instruments: list[str]
    activity_categories: list[str]
    award_ceiling: float | None
    award_floor: float | None
    cost_sharing: bool | None
    attachments: list[Attachment]
    document_urls: list[str]
    attachment_count: int
    full_announcement_present: bool
    analysis: dict[str, Any]
    eligibility_gate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["attachments"] = [item.to_dict() for item in self.attachments]
        return data


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _descriptions(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []

    output: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        value = str(item.get("description", "")).strip()

        if value and value not in output:
            output.append(value)

    return output


def _attachments(detail: dict[str, Any]) -> list[Attachment]:
    output: list[Attachment] = []

    for folder in detail.get("synopsisAttachmentFolders") or []:
        if not isinstance(folder, dict):
            continue

        folder_type = str(folder.get("folderType", "")).strip()
        folder_name = str(folder.get("folderName", "")).strip()

        for item in folder.get("synopsisAttachments") or []:
            if not isinstance(item, dict):
                continue

            raw_id = item.get("id")
            raw_size = item.get("fileLobSize")

            output.append(
                Attachment(
                    id=raw_id if isinstance(raw_id, int) else None,
                    file_name=str(item.get("fileName", "")).strip(),
                    mime_type=str(item.get("mimeType", "")).strip(),
                    description=" | ".join(
                        part
                        for part in (
                            folder_type,
                            folder_name,
                            str(item.get("fileDescription", "")).strip(),
                        )
                        if part
                    ),
                    size_bytes=raw_size if isinstance(raw_size, int) else None,
                )
            )

    return output


def _document_urls(detail: dict[str, Any]) -> list[str]:
    output: list[str] = []

    for item in detail.get("synopsisDocumentURLs") or []:
        if isinstance(item, str):
            value = item.strip()
        elif isinstance(item, dict):
            value = str(
                item.get("url")
                or item.get("documentURL")
                or item.get("link")
                or ""
            ).strip()
        else:
            continue

        if value and value not in output:
            output.append(value)

    return output


def _eligibility_gate(
    *,
    title: str,
    eligibility: list[str],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    title_lower = title.lower()
    joined = " ".join(eligibility).lower()

    blockers = list(analysis.get("blockers", []))

    nonprofit_allowed = any(
        term in joined
        for term in (
            "nonprofit",
            "non-profit",
            "501(c)(3)",
            "501c3",
            "faith-based",
            "community-based",
        )
    )

    research_title_signals = (
        "clinical and translational science award",
        "ctsa",
        "clinical trial",
        "research in the formation of engineers",
        "advanced cyberinfrastructure",
        "research access",
        "research initiative",
        "national defense education program",
        "stem consortia",
        "postdoctoral",
        "doctoral fellowship",
        "research fellowship",
    )

    if any(signal in title_lower for signal in research_title_signals):
        blockers.append(
            "academic/research opportunity outside Broken Growth Ministries program scope"
        )

    government_terms = (
        "state governments",
        "county governments",
        "city or township governments",
        "special district governments",
        "public housing authorities",
        "native american tribal governments",
    )

    academic_terms = (
        "institutions of higher education",
        "private institutions of higher education",
        "public and state controlled institutions",
    )

    government_only = bool(eligibility) and all(
        any(term in item.lower() for term in government_terms)
        for item in eligibility
    )

    individual_only = bool(eligibility) and all(
        "individual" in item.lower()
        for item in eligibility
    )

    academic_only = bool(eligibility) and all(
        any(term in item.lower() for term in academic_terms)
        for item in eligibility
    )

    if government_only:
        blockers.append("eligibility appears limited to government entities")

    if individual_only:
        blockers.append("eligibility appears limited to individuals")

    if academic_only:
        blockers.append(
            "eligibility appears limited to higher-education institutions"
        )

    blockers = list(dict.fromkeys(blockers))

    if blockers:
        decision = "REJECT"
    elif nonprofit_allowed:
        decision = "PROCEED"
    else:
        decision = "VERIFY"

    return {
        "eligible_or_requires_review": decision != "REJECT",
        "nonprofit_explicitly_allowed": nonprofit_allowed,
        "government_only": government_only,
        "individual_only": individual_only,
        "academic_only": academic_only,
        "blockers": blockers,
        "decision": decision,
        "title": title,
    }


def get_full_nofo_intelligence(
    opportunity_id: str | int,
) -> FullNofoResult:
    detail = fetch_opportunity(opportunity_id)

    synopsis = detail.get("synopsis") or {}
    agency_details = detail.get("agencyDetails") or {}

    title = str(detail.get("opportunityTitle", "")).strip()
    number = str(detail.get("opportunityNumber", "")).strip()

    funder = str(
        synopsis.get("agencyName")
        or agency_details.get("agencyName")
        or ""
    ).strip()

    eligibility = _descriptions(synopsis.get("applicantTypes"))
    instruments = _descriptions(synopsis.get("fundingInstruments"))
    categories = _descriptions(synopsis.get("fundingActivityCategories"))

    attachments = _attachments(detail)
    document_urls = _document_urls(detail)

    analysis_text = "\n".join(
        value
        for value in (
            title,
            number,
            funder,
            str(synopsis.get("synopsisDesc", "")).strip(),
            " ".join(eligibility),
            " ".join(instruments),
            " ".join(categories),
            str(detail.get("originalDueDateDesc", "")).strip(),
        )
        if value
    )

    if len(analysis_text.strip()) < 20:
        analysis_text = f"{title} {funder} opportunity details unavailable."

    analysis = analyze_nofo(
        analysis_text,
        title=title,
        funder=funder,
        opportunity_number=number,
    ).to_dict()

    gate = _eligibility_gate(
        title=title,
        eligibility=eligibility,
        analysis=analysis,
    )

    full_announcement_present = any(
        (
            "full announcement" in attachment.description.lower()
            or "nofo" in attachment.file_name.lower()
            or "notice of funding" in attachment.file_name.lower()
        )
        for attachment in attachments
    )

    return FullNofoResult(
        opportunity_id=str(detail.get("id", opportunity_id)),
        opportunity_number=number,
        title=title,
        funder=funder,
        eligibility=eligibility,
        funding_instruments=instruments,
        activity_categories=categories,
        award_ceiling=_to_float(synopsis.get("awardCeiling")),
        award_floor=_to_float(synopsis.get("awardFloor")),
        cost_sharing=(
            synopsis.get("costSharing")
            if isinstance(synopsis.get("costSharing"), bool)
            else None
        ),
        attachments=attachments,
        document_urls=document_urls,
        attachment_count=len(attachments),
        full_announcement_present=full_announcement_present,
        analysis=analysis,
        eligibility_gate=gate,
    )
