from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from grantbot.core.database import connection, utc_now
from grantbot.master.database import initialize_master_schema, list_revisions
from grantbot.review.staging_v17 import get_workspace


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _validate_id(value: str, label: str) -> str:
    clean = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", clean) or ".." in clean:
        raise ValueError(f"Invalid {label}")
    return clean


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _packet_dirs(workspace_id: str) -> tuple[Path, Path]:
    base = _root() / "data"
    upload_dir = base / "packet_uploads_v19" / workspace_id
    packet_dir = base / "packets_v19" / workspace_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    packet_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir, packet_dir


def controlled_upload_path(workspace_id: str, filename: str) -> Path:
    workspace_id = _validate_id(workspace_id, "workspace_id")
    name = Path(filename).name
    if not name or name in {".", ".."}:
        raise ValueError("Invalid filename")
    upload_dir, _ = _packet_dirs(workspace_id)
    target = (upload_dir / name).resolve()
    if upload_dir.resolve() not in target.parents:
        raise ValueError("Upload path escaped controlled directory")
    return target


def build_packet(workspace_id: str) -> dict[str, Any]:
    initialize_master_schema()
    workspace_id = _validate_id(workspace_id, "workspace_id")
    workspace = get_workspace(workspace_id)
    _, packet_dir = _packet_dirs(workspace_id)
    with connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(revision), 0) AS revision FROM application_packets_v19 WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        revision = int(row["revision"]) + 1
    packet_id = uuid.uuid4().hex
    now = utc_now()
    revisions = list_revisions(workspace_id)
    manifest = {
        "packet_id": packet_id,
        "workspace_id": workspace_id,
        "packet_revision": revision,
        "opportunity_id": workspace.get("opportunity_id"),
        "title": workspace.get("title"),
        "funder": workspace.get("funder"),
        "workspace_stage": workspace.get("stage"),
        "human_approved": bool(workspace.get("human_approved")),
        "writer_revisions": [
            {
                "revision_id": item["revision_id"],
                "task_id": item["task_id"],
                "version": item["version"],
                "status": item["status"],
            }
            for item in revisions
        ],
        "created_at": now,
        "submission_enabled": False,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = packet_dir / f"packet_{revision:03d}_manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    archive_path = packet_dir / f"packet_{revision:03d}.zip"

    with connection() as conn:
        conn.execute(
            """
            INSERT INTO application_packets_v19(
                packet_id, workspace_id, revision, status, manifest_json,
                manifest_sha256, archive_path, human_approved, approved_by,
                approved_at, sealed_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, 0, '', '', '', ?, ?)
            """,
            (
                packet_id,
                workspace_id,
                revision,
                json.dumps(manifest, ensure_ascii=False),
                manifest_sha,
                str(archive_path),
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO packet_events_v19(event_id, packet_id, event_type, actor, note, created_at)
            VALUES (?, ?, 'PACKET_CREATED', 'system', ?, ?)
            """,
            (uuid.uuid4().hex, packet_id, f"Packet revision {revision} created.", now),
        )
    return get_packet(packet_id)


def register_attachment(
    packet_id: str,
    *,
    source_path: str,
    logical_name: str,
    required: bool = True,
    media_type: str | None = None,
) -> dict[str, Any]:
    initialize_master_schema()
    packet = get_packet(packet_id)
    workspace_id = packet["workspace_id"]
    upload_dir, packet_dir = _packet_dirs(workspace_id)
    source = Path(source_path).expanduser().resolve()
    if upload_dir.resolve() not in source.parents:
        raise ValueError("Attachments must originate from the controlled packet upload directory")
    if not source.is_file():
        raise FileNotFoundError(str(source))
    clean_name = Path(logical_name).name
    if not clean_name:
        raise ValueError("logical_name is required")
    destination_dir = packet_dir / f"packet_{int(packet['revision']):03d}_files"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / clean_name
    shutil.copy2(source, destination)
    attachment_id = uuid.uuid4().hex
    detected = media_type or mimetypes.guess_type(destination.name)[0] or "application/octet-stream"
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO packet_attachments_v19(
                attachment_id, packet_id, logical_name, stored_path, sha256,
                byte_size, media_type, required, verified, verified_by,
                verified_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, '', '', ?)
            """,
            (
                attachment_id,
                packet_id,
                clean_name,
                str(destination),
                _sha256(destination),
                destination.stat().st_size,
                detected,
                int(required),
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO packet_events_v19(event_id, packet_id, event_type, actor, note, created_at)
            VALUES (?, ?, 'ATTACHMENT_ADDED', 'system', ?, ?)
            """,
            (uuid.uuid4().hex, packet_id, clean_name, now),
        )
    return get_packet(packet_id)


def verify_attachment(packet_id: str, attachment_id: str, *, actor: str) -> dict[str, Any]:
    actor = actor.strip()
    if not actor:
        raise ValueError("actor is required")
    now = utc_now()
    with connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM packet_attachments_v19
            WHERE packet_id=? AND attachment_id=?
            """,
            (packet_id, attachment_id),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Attachment not found: {attachment_id}")
        path = Path(str(row["stored_path"]))
        if not path.is_file() or _sha256(path) != str(row["sha256"]):
            raise ValueError("Attachment hash verification failed")
        conn.execute(
            """
            UPDATE packet_attachments_v19
            SET verified=1, verified_by=?, verified_at=?
            WHERE packet_id=? AND attachment_id=?
            """,
            (actor, now, packet_id, attachment_id),
        )
    return get_packet(packet_id)


def approve_packet(packet_id: str, *, actor: str, note: str) -> dict[str, Any]:
    actor = actor.strip()
    note = note.strip()
    if not actor or not note:
        raise ValueError("actor and note are required")
    packet = get_packet(packet_id)
    workspace = get_workspace(packet["workspace_id"])
    if not workspace.get("human_approved"):
        raise ValueError("V17 human application approval is required before packet approval")
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            UPDATE application_packets_v19
            SET human_approved=1, approved_by=?, approved_at=?, status='APPROVED', updated_at=?
            WHERE packet_id=?
            """,
            (actor, now, now, packet_id),
        )
        conn.execute(
            """
            INSERT INTO packet_events_v19(event_id, packet_id, event_type, actor, note, created_at)
            VALUES (?, ?, 'PACKET_APPROVED', ?, ?, ?)
            """,
            (uuid.uuid4().hex, packet_id, actor, note, now),
        )
    return get_packet(packet_id)


def finalize_packet(packet_id: str, *, actor: str) -> dict[str, Any]:
    packet = get_packet(packet_id)
    workspace = get_workspace(packet["workspace_id"])
    if workspace.get("stage") != "READY_FOR_SUBMISSION":
        raise ValueError("Workspace must be READY_FOR_SUBMISSION before packet sealing")
    if not packet["human_approved"]:
        raise ValueError("Packet human approval is required before sealing")
    required_unverified = [
        item for item in packet["attachments"]
        if item["required"] and not item["verified"]
    ]
    if required_unverified:
        raise ValueError("All required packet attachments must be verified before sealing")

    archive_path = Path(packet["archive_path"])
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = dict(packet["manifest"])
    manifest["sealed_at"] = utc_now()
    manifest["submission_enabled"] = False
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        for attachment in packet["attachments"]:
            source = Path(attachment["stored_path"])
            if not source.is_file() or _sha256(source) != attachment["sha256"]:
                raise ValueError(f"Attachment integrity failure: {attachment['logical_name']}")
            archive.write(source, arcname=f"attachments/{attachment['logical_name']}")

    archive_sha = _sha256(archive_path)
    now = utc_now()
    manifest["archive_sha256"] = archive_sha
    with connection() as conn:
        conn.execute(
            """
            UPDATE application_packets_v19
            SET status='SEALED', manifest_json=?, manifest_sha256=?, sealed_at=?, updated_at=?
            WHERE packet_id=?
            """,
            (
                json.dumps(manifest, ensure_ascii=False),
                hashlib.sha256(manifest_bytes).hexdigest(),
                now,
                now,
                packet_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO packet_events_v19(event_id, packet_id, event_type, actor, note, created_at)
            VALUES (?, ?, 'PACKET_SEALED', ?, ?, ?)
            """,
            (uuid.uuid4().hex, packet_id, actor.strip() or "authorized-reviewer", archive_sha, now),
        )
    return get_packet(packet_id)


def get_packet(packet_id: str) -> dict[str, Any]:
    initialize_master_schema()
    packet_id = _validate_id(packet_id, "packet_id")
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM application_packets_v19 WHERE packet_id=?",
            (packet_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Packet not found: {packet_id}")
        attachments = conn.execute(
            "SELECT * FROM packet_attachments_v19 WHERE packet_id=? ORDER BY logical_name",
            (packet_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM packet_events_v19 WHERE packet_id=? ORDER BY created_at",
            (packet_id,),
        ).fetchall()
    item = dict(row)
    item["human_approved"] = bool(item["human_approved"])
    try:
        item["manifest"] = json.loads(str(item.pop("manifest_json")))
    except json.JSONDecodeError:
        item["manifest"] = {}
    output_attachments = []
    for attachment in attachments:
        data = dict(attachment)
        data["required"] = bool(data["required"])
        data["verified"] = bool(data["verified"])
        output_attachments.append(data)
    item["attachments"] = output_attachments
    item["events"] = [dict(event) for event in events]
    item["submission_enabled"] = False
    return item
