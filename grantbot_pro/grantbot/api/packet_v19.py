from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from grantbot.packaging.packet_v19 import (
    approve_packet,
    build_packet,
    controlled_upload_path,
    finalize_packet,
    get_packet,
    register_attachment,
    verify_attachment,
)


router = APIRouter(prefix="/v19/packet", tags=["GrantBot Packet Compliance v19"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.post("/build/{workspace_id}")
def build(workspace_id: str) -> dict[str, Any]:
    try:
        return build_packet(workspace_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/{packet_id}")
def get(packet_id: str) -> dict[str, Any]:
    try:
        return get_packet(packet_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/{packet_id}/upload")
async def upload(
    packet_id: str,
    workspace_id: str = Form(),
    logical_name: str = Form(),
    required: bool = Form(True),
    file: UploadFile = File(),
) -> dict[str, Any]:
    target: Path | None = None
    try:
        target = controlled_upload_path(workspace_id, file.filename or logical_name)
        total = 0
        with target.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 50 * 1024 * 1024:
                    raise ValueError("Attachment exceeds 50 MB limit")
                handle.write(chunk)
        return register_attachment(
            packet_id,
            source_path=str(target),
            logical_name=logical_name,
            required=required,
            media_type=file.content_type,
        )
    except Exception as exc:
        if target is not None and target.exists():
            target.unlink(missing_ok=True)
        raise _error(exc) from exc
    finally:
        await file.close()


@router.post("/{packet_id}/attachments/{attachment_id}/verify")
def verify(packet_id: str, attachment_id: str, actor: str = Form()) -> dict[str, Any]:
    try:
        return verify_attachment(packet_id, attachment_id, actor=actor)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/{packet_id}/approve")
def approve(packet_id: str, actor: str = Form(), note: str = Form()) -> dict[str, Any]:
    try:
        return approve_packet(packet_id, actor=actor, note=note)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/{packet_id}/seal")
def seal(packet_id: str, actor: str = Form()) -> dict[str, Any]:
    try:
        return finalize_packet(packet_id, actor=actor)
    except Exception as exc:
        raise _error(exc) from exc
