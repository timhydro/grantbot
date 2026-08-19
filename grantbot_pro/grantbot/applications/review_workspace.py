from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    NEEDS_USER = "NEEDS_USER"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    INELIGIBLE = "INELIGIBLE"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class ReviewField:
    label: str
    value: str | None
    source: str
    requires_user_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class ReviewPacket:
    opportunity_id: str
    opportunity_name: str
    funding_type: str
    status: ReviewStatus
    source_url: str
    deadline: str | None
    requested_amount: str | None
    fields: list[ReviewField]
    missing_items: list[str]
    submission_steps: list[str]
    notes: list[str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def application_root() -> Path:
    override = os.getenv("GRANTBOT_APPLICATION_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "data" / "applications"


def _safe_id(value: str) -> str:
    result = _SAFE_RE.sub("_", value.strip()).strip("._-")
    if not result:
        raise ValueError("opportunity_id cannot be empty")
    return result[:120]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _render_markdown(packet: ReviewPacket) -> str:
    lines = [
        f"# {packet.opportunity_name}",
        "",
        f"**Funding type:** {packet.funding_type}",
        f"**Status:** {packet.status.value}",
        f"**Deadline:** {packet.deadline or 'Not stated / rolling'}",
        f"**Requested amount:** {packet.requested_amount or 'To be determined'}",
        f"**Source:** {packet.source_url}",
        "",
        "## Prefilled Fields",
        "",
    ]
    for field in packet.fields:
        confirm = " — USER CONFIRMATION REQUIRED" if field.requires_user_confirmation else ""
        value = field.value if field.value not in {None, ""} else "[MISSING]"
        lines.extend([
            f"### {field.label}{confirm}",
            str(value),
            f"_Source: {field.source}_",
            "",
        ])

    lines.extend(["## Missing / Human-Required Items", ""])
    if packet.missing_items:
        lines.extend(f"- [ ] {item}" for item in packet.missing_items)
    else:
        lines.append("- [x] No missing items recorded")

    lines.extend(["", "## Submission Steps", ""])
    lines.extend(f"{idx}. {step}" for idx, step in enumerate(packet.submission_steps, start=1))

    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in packet.notes)
    lines.append("")
    return "\n".join(lines)


def save_review_packet(packet: ReviewPacket, *, root: Path | None = None) -> Path:
    root = root or application_root()
    folder = root / _safe_id(packet.opportunity_id)
    payload = json.dumps(packet.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    _atomic_write(folder / "application.json", payload)
    _atomic_write(folder / "REVIEW.md", _render_markdown(packet))
    _atomic_write(
        folder / "STATUS.json",
        json.dumps(
            {
                "status": packet.status.value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "missing_count": len(packet.missing_items),
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
    )
    return folder


def new_review_packet(
    *,
    opportunity_id: str,
    opportunity_name: str,
    funding_type: str,
    source_url: str,
    fields: list[ReviewField],
    missing_items: list[str] | None = None,
    submission_steps: list[str] | None = None,
    notes: list[str] | None = None,
    deadline: str | None = None,
    requested_amount: str | None = None,
    status: ReviewStatus | None = None,
) -> ReviewPacket:
    missing = list(dict.fromkeys(missing_items or []))
    if status is None:
        status = ReviewStatus.NEEDS_USER if missing else ReviewStatus.READY_FOR_REVIEW
    return ReviewPacket(
        opportunity_id=opportunity_id,
        opportunity_name=opportunity_name,
        funding_type=funding_type,
        status=status,
        source_url=source_url,
        deadline=deadline,
        requested_amount=requested_amount,
        fields=fields,
        missing_items=missing,
        submission_steps=list(submission_steps or []),
        notes=list(notes or []),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def list_review_packets(*, root: Path | None = None) -> list[dict[str, Any]]:
    root = root or application_root()
    if not root.exists():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/application.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            result.append(data)
    return result
