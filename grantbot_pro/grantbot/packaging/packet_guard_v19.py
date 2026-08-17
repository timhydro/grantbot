from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

from grantbot.core.database import connection, utc_now
from grantbot.master.database import initialize_master_schema, list_revisions
from grantbot.packaging.packet_v19 import (
    build_packet,
    controlled_upload_path,
    get_packet,
    register_attachment as _register_attachment,
)
from grantbot.review.staging_v17 import get_workspace


KNOWN_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
}


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect(path: Path) -> str:
    header = path.read_bytes()[:32]
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header.startswith(b"PK\x03\x04") and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
        if "word/document.xml" in names:
            return KNOWN_TYPES[".docx"]
        if "xl/workbook.xml" in names:
            return KNOWN_TYPES[".xlsx"]
        if "ppt/presentation.xml" in names:
            return KNOWN_TYPES[".pptx"]
        return "application/zip"
    raw = path.read_bytes()[:262144]
    if b"\x00" not in raw:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if text:
            if path.suffix.lower() == ".csv":
                return "text/csv"
            if path.suffix.lower() == ".json":
                try:
                    json.loads(text)
                    return "application/json"
                except json.JSONDecodeError:
                    return "text/plain"
            return "text/plain"
    return "application/octet-stream"


def _ensure_guard_schema() -> None:
    initialize_master_schema()
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS packet_seal_registry_v19 (
                packet_id TEXT PRIMARY KEY,
                snapshot_json TEXT NOT NULL,
                snapshot_sha256 TEXT NOT NULL,
                archive_sha256 TEXT NOT NULL DEFAULT '',
                approved_by TEXT NOT NULL,
                approved_at TEXT NOT NULL,
                sealed_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(packet_id) REFERENCES application_packets_v19(packet_id)
                    ON DELETE CASCADE
            )
            """
        )


def _latest_revisions(workspace_id: str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in list_revisions(workspace_id):
        task_id = str(item.get("task_id", "")).strip()
        if not task_id:
            continue
        if task_id not in latest or int(item.get("version", 0)) > int(
            latest[task_id].get("version", 0)
        ):
            latest[task_id] = item
    return [latest[key] for key in sorted(latest)]


def _revision_record(item: dict[str, Any]) -> dict[str, Any]:
    provenance = {
        "revision_id": str(item.get("revision_id", "")),
        "task_id": str(item.get("task_id", "")),
        "version": int(item.get("version", 0)),
        "status": str(item.get("status", "")),
        "facts": item.get("facts", []),
        "claims": item.get("claims", {}),
        "quality": item.get("quality", {}),
        "provider": str(item.get("provider", "")),
        "model": str(item.get("model", "")),
    }
    return {
        **provenance,
        "content_sha256": _text_sha(str(item.get("content", ""))),
        "provenance_sha256": _text_sha(_json_text(provenance)),
    }


def _snapshot(
    packet: dict[str, Any], actor: str, note: str, approved_at: str
) -> dict[str, Any]:
    workspace = get_workspace(packet["workspace_id"])
    return {
        "packet_id": packet["packet_id"],
        "workspace_id": packet["workspace_id"],
        "packet_revision": int(packet["revision"]),
        "opportunity_id": workspace.get("opportunity_id"),
        "title": workspace.get("title"),
        "funder": workspace.get("funder"),
        "workspace_stage": workspace.get("stage"),
        "writer_revisions": [
            _revision_record(item) for item in _latest_revisions(packet["workspace_id"])
        ],
        "attachments": [
            {
                "attachment_id": item["attachment_id"],
                "logical_name": item["logical_name"],
                "sha256": item["sha256"],
                "byte_size": int(item["byte_size"]),
                "media_type": item["media_type"],
                "required": bool(item["required"]),
                "verified": bool(item["verified"]),
                "verified_by": item["verified_by"],
                "verified_at": item["verified_at"],
            }
            for item in sorted(
                packet["attachments"], key=lambda row: row["logical_name"].casefold()
            )
        ],
        "approval": {
            "approved_by": actor,
            "approved_at": approved_at,
            "note": note,
        },
        "frozen": True,
        "submission_enabled": False,
    }


def _registry(packet_id: str) -> dict[str, Any] | None:
    _ensure_guard_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM packet_seal_registry_v19 WHERE packet_id=?",
            (packet_id,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["snapshot"] = json.loads(str(data.pop("snapshot_json")))
    return data


def _assert_draft(packet: dict[str, Any]) -> None:
    if packet["status"] != "DRAFT":
        raise ValueError(
            f"Packet is {packet['status']} and immutable; "
            "create a new packet revision for changes"
        )


def register_attachment(
    packet_id: str,
    *,
    source_path: str,
    logical_name: str,
    required: bool = True,
    media_type: str | None = None,
) -> dict[str, Any]:
    packet = get_packet(packet_id)
    _assert_draft(packet)
    clean = Path(logical_name).name
    if not clean:
        raise ValueError("logical_name is required")
    if any(
        item["logical_name"].casefold() == clean.casefold()
        for item in packet["attachments"]
    ):
        raise ValueError(f"Duplicate attachment logical_name: {clean}")
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(str(source))
    detected = _detect(source)
    expected = KNOWN_TYPES.get(Path(clean).suffix.lower())
    if expected and detected != expected:
        raise ValueError(
            f"File content does not match extension: "
            f"detected {detected}, expected {expected}"
        )
    declared = (media_type or "").strip().lower()
    if (
        declared
        and declared != "application/octet-stream"
        and declared != detected.lower()
    ):
        raise ValueError(
            f"Declared media type {declared} does not match "
            f"detected media type {detected}"
        )
    return _register_attachment(
        packet_id,
        source_path=source_path,
        logical_name=clean,
        required=required,
        media_type=detected,
    )


def verify_attachment(
    packet_id: str, attachment_id: str, *, actor: str
) -> dict[str, Any]:
    packet = get_packet(packet_id)
    _assert_draft(packet)
    actor = actor.strip()
    if not actor:
        raise ValueError("actor is required")
    match = next(
        (
            item
            for item in packet["attachments"]
            if item["attachment_id"] == attachment_id
        ),
        None,
    )
    if match is None:
        raise FileNotFoundError(f"Attachment not found: {attachment_id}")
    path = Path(match["stored_path"])
    if not path.is_file() or _file_sha(path) != match["sha256"]:
        raise ValueError("Attachment hash verification failed")
    if _detect(path) != match["media_type"]:
        raise ValueError("Attachment media-type verification failed")
    now = utc_now()
    with connection() as conn:
        conn.execute(
            "UPDATE packet_attachments_v19 "
            "SET verified=1, verified_by=?, verified_at=? "
            "WHERE packet_id=? AND attachment_id=?",
            (actor, now, packet_id, attachment_id),
        )
        conn.execute(
            "INSERT INTO packet_events_v19("
            "event_id,packet_id,event_type,actor,note,created_at) "
            "VALUES(?,?,'ATTACHMENT_VERIFIED',?,?,?)",
            (uuid.uuid4().hex, packet_id, actor, match["logical_name"], now),
        )
    return get_packet(packet_id)


def approve_packet(packet_id: str, *, actor: str, note: str) -> dict[str, Any]:
    _ensure_guard_schema()
    packet = get_packet(packet_id)
    _assert_draft(packet)
    actor, note = actor.strip(), note.strip()
    if not actor or not note:
        raise ValueError("actor and note are required")
    workspace = get_workspace(packet["workspace_id"])
    if not workspace.get("human_approved"):
        raise ValueError(
            "V17 human application approval is required before packet approval"
        )
    if any(not item["verified"] for item in packet["attachments"]):
        raise ValueError(
            "Every included packet attachment must be verified before approval"
        )
    now = utc_now()
    snapshot = _snapshot(packet, actor, note, now)
    snapshot_text = _json_text(snapshot)
    snapshot_sha = _text_sha(snapshot_text)
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE application_packets_v19 "
            "SET status='APPROVED', human_approved=1, approved_by=?, "
            "approved_at=?, manifest_json=?, manifest_sha256=?, updated_at=? "
            "WHERE packet_id=? AND status='DRAFT'",
            (actor, now, snapshot_text, snapshot_sha, now, packet_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Packet state changed before approval; reload and retry")
        conn.execute(
            "INSERT INTO packet_seal_registry_v19("
            "packet_id,snapshot_json,snapshot_sha256,archive_sha256,"
            "approved_by,approved_at,sealed_at) VALUES(?,?,?,'',?,?,'')",
            (packet_id, snapshot_text, snapshot_sha, actor, now),
        )
        conn.execute(
            "INSERT INTO packet_events_v19("
            "event_id,packet_id,event_type,actor,note,created_at) "
            "VALUES(?,?,'PACKET_APPROVED',?,?,?)",
            (uuid.uuid4().hex, packet_id, actor, note, now),
        )
    return get_packet(packet_id)


def _snapshot_issues(
    packet: dict[str, Any], snapshot: dict[str, Any]
) -> list[str]:
    issues: list[str] = []
    current = {
        str(item.get("revision_id")): item
        for item in list_revisions(packet["workspace_id"])
    }
    for expected in snapshot.get("writer_revisions", []):
        revision = current.get(str(expected.get("revision_id")))
        if revision is None:
            issues.append(
                f"Missing writer revision: {expected.get('revision_id')}"
            )
            continue
        record = _revision_record(revision)
        if record["content_sha256"] != expected.get("content_sha256"):
            issues.append(
                f"Writer revision changed: {expected.get('revision_id')}"
            )
        if record["provenance_sha256"] != expected.get("provenance_sha256"):
            issues.append(
                f"Writer provenance changed: {expected.get('revision_id')}"
            )
    current_latest = {
        (r["task_id"], r["revision_id"], r["version"])
        for r in map(
            _revision_record,
            _latest_revisions(packet["workspace_id"]),
        )
    }
    expected_latest = {
        (r["task_id"], r["revision_id"], r["version"])
        for r in snapshot.get("writer_revisions", [])
    }
    if current_latest != expected_latest:
        issues.append("A newer writer revision exists; rebuild the packet")
    expected_attachments = {
        str(item["attachment_id"]): item
        for item in snapshot.get("attachments", [])
    }
    current_attachments = {
        str(item["attachment_id"]): item for item in packet["attachments"]
    }
    if set(current_attachments) != set(expected_attachments):
        issues.append("Packet attachment set changed after approval")
    for attachment_id, expected in expected_attachments.items():
        attachment = current_attachments.get(attachment_id)
        if attachment is None:
            continue
        path = Path(attachment["stored_path"])
        if attachment["logical_name"] != expected["logical_name"]:
            issues.append(
                f"Attachment name changed: {expected['logical_name']}"
            )
        if attachment["sha256"] != expected["sha256"]:
            issues.append(
                f"Attachment database hash changed: {expected['logical_name']}"
            )
        if attachment["media_type"] != expected["media_type"]:
            issues.append(
                f"Attachment media type changed: {expected['logical_name']}"
            )
        if not attachment["verified"]:
            issues.append(
                f"Unverified attachment: {expected['logical_name']}"
            )
        elif not path.is_file() or _file_sha(path) != expected["sha256"]:
            issues.append(
                f"Attachment integrity failure: {expected['logical_name']}"
            )
        elif _detect(path) != expected["media_type"]:
            issues.append(
                f"Attachment content type changed: {expected['logical_name']}"
            )
    return issues


def finalize_packet(packet_id: str, *, actor: str) -> dict[str, Any]:
    packet = get_packet(packet_id)
    actor = actor.strip()
    if not actor:
        raise ValueError("actor is required")
    if packet["status"] != "APPROVED":
        raise ValueError("Packet must be APPROVED before sealing")
    workspace = get_workspace(packet["workspace_id"])
    if workspace.get("stage") != "READY_FOR_SUBMISSION":
        raise ValueError(
            "Workspace must be READY_FOR_SUBMISSION before packet sealing"
        )
    registry = _registry(packet_id)
    if registry is None:
        raise ValueError("Packet approval snapshot is missing")
    issues = _snapshot_issues(packet, registry["snapshot"])
    if issues:
        raise ValueError("; ".join(issues))
    snapshot_text = _json_text(registry["snapshot"])
    if packet.get("manifest_sha256") != registry["snapshot_sha256"]:
        raise ValueError("Packet manifest no longer matches the approved snapshot")
    if _text_sha(_json_text(packet.get("manifest") or {})) != registry[
        "snapshot_sha256"
    ]:
        raise ValueError("Packet manifest content changed after approval")
    if _text_sha(snapshot_text) != registry["snapshot_sha256"]:
        raise ValueError("Approval snapshot hash mismatch")
    revision_map = {
        str(item["revision_id"]): item
        for item in list_revisions(packet["workspace_id"])
    }
    archive_path = Path(packet["archive_path"])
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr("manifest.json", snapshot_text.encode("utf-8"))
        for expected in registry["snapshot"].get("writer_revisions", []):
            revision = revision_map[str(expected["revision_id"])]
            task_id = str(expected["task_id"])
            archive.writestr(
                f"narratives/{task_id}.txt",
                str(revision.get("content", "")).encode("utf-8"),
            )
            provenance = {
                key: revision.get(key)
                for key in (
                    "revision_id",
                    "task_id",
                    "version",
                    "status",
                    "facts",
                    "claims",
                    "quality",
                    "provider",
                    "model",
                )
            }
            archive.writestr(
                f"provenance/{task_id}.json",
                _json_text(provenance).encode("utf-8"),
            )
        attachment_by_id = {
            str(item["attachment_id"]): item for item in packet["attachments"]
        }
        for expected in registry["snapshot"].get("attachments", []):
            attachment = attachment_by_id[str(expected["attachment_id"])]
            archive.write(
                Path(attachment["stored_path"]),
                arcname=f"attachments/{expected['logical_name']}",
            )
    archive_sha = _file_sha(archive_path)
    now = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE application_packets_v19 "
            "SET status='SEALED', sealed_at=?, updated_at=? "
            "WHERE packet_id=? AND status='APPROVED'",
            (now, now, packet_id),
        )
        if cursor.rowcount != 1:
            archive_path.unlink(missing_ok=True)
            raise ValueError("Packet state changed before sealing; archive discarded")
        conn.execute(
            "UPDATE packet_seal_registry_v19 "
            "SET archive_sha256=?, sealed_at=? WHERE packet_id=?",
            (archive_sha, now, packet_id),
        )
        conn.execute(
            "INSERT INTO packet_events_v19("
            "event_id,packet_id,event_type,actor,note,created_at) "
            "VALUES(?,?,'PACKET_SEALED',?,?,?)",
            (uuid.uuid4().hex, packet_id, actor, archive_sha, now),
        )
    return get_packet(packet_id)


def verify_packet_integrity(packet_id: str) -> dict[str, Any]:
    packet = get_packet(packet_id)
    registry = _registry(packet_id)
    issues: list[str] = []
    if registry is None:
        issues.append("Packet approval snapshot is missing")
    else:
        snapshot_text = _json_text(registry["snapshot"])
        if _text_sha(snapshot_text) != registry["snapshot_sha256"]:
            issues.append("Approval snapshot hash mismatch")
        if packet["manifest_sha256"] != registry["snapshot_sha256"]:
            issues.append("Packet manifest does not match approval snapshot")
        if _text_sha(_json_text(packet.get("manifest") or {})) != registry[
            "snapshot_sha256"
        ]:
            issues.append("Packet manifest content does not match approval snapshot")
        issues.extend(_snapshot_issues(packet, registry["snapshot"]))
        if packet["status"] == "SEALED":
            archive_path = Path(packet["archive_path"])
            if not archive_path.is_file():
                issues.append("Sealed archive is missing")
            elif _file_sha(archive_path) != registry["archive_sha256"]:
                issues.append("Sealed archive hash mismatch")
            else:
                try:
                    with zipfile.ZipFile(archive_path) as archive:
                        if archive.read("manifest.json").decode("utf-8") != snapshot_text:
                            issues.append("Archived manifest mismatch")
                        for attachment in registry["snapshot"].get(
                            "attachments", []
                        ):
                            data = archive.read(
                                f"attachments/{attachment['logical_name']}"
                            )
                            if hashlib.sha256(data).hexdigest() != attachment[
                                "sha256"
                            ]:
                                issues.append(
                                    "Archived attachment mismatch: "
                                    f"{attachment['logical_name']}"
                                )
                        for revision in registry["snapshot"].get(
                            "writer_revisions", []
                        ):
                            data = archive.read(
                                f"narratives/{revision['task_id']}.txt"
                            )
                            if hashlib.sha256(data).hexdigest() != revision[
                                "content_sha256"
                            ]:
                                issues.append(
                                    "Archived narrative mismatch: "
                                    f"{revision['task_id']}"
                                )
                            provenance = archive.read(
                                f"provenance/{revision['task_id']}.json"
                            ).decode("utf-8")
                            if _text_sha(provenance) != revision[
                                "provenance_sha256"
                            ]:
                                issues.append(
                                    "Archived provenance mismatch: "
                                    f"{revision['task_id']}"
                                )
                except (OSError, KeyError, zipfile.BadZipFile) as exc:
                    issues.append(
                        "Archive validation failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
    return {
        "packet_id": packet_id,
        "status": packet["status"],
        "safe": not issues,
        "issues": issues,
        "archive_sha256": "" if registry is None else registry["archive_sha256"],
        "submission_enabled": False,
    }
