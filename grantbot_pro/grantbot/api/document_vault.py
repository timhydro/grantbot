from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from grantbot.security.auth import (
    ADMIN,
    AUTHORIZED_REPRESENTATIVE,
    FINANCIAL_REVIEWER,
    GRANT_WRITER,
    REVIEWER,
    Principal,
    require_roles,
)
from grantbot.vault import (
    add_requirement,
    approve_document,
    attach_document_to_packet,
    get_document,
    list_documents,
    list_events,
    list_links,
    list_requirements,
    link_document,
    readiness_dashboard,
    resolve_document_path,
    review_document,
    set_requirement_active,
    store_document,
)
from grantbot.vault.schema import CATEGORIES, REQUIREMENT_SCOPES


router = APIRouter(
    prefix="/master/vault",
    tags=["GrantBot Organizational Document Vault"],
)

READ_ROLES = (
    ADMIN,
    AUTHORIZED_REPRESENTATIVE,
    FINANCIAL_REVIEWER,
    GRANT_WRITER,
    REVIEWER,
)


class ReviewRequest(BaseModel):
    verification_state: str = Field(min_length=3, max_length=30)
    review_note: str = Field(min_length=1, max_length=5000)
    review_due_date: str = Field(default="", max_length=10)


class LinkRequest(BaseModel):
    entity_type: str = Field(min_length=2, max_length=80)
    entity_id: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=500)


class RequirementRequest(BaseModel):
    requirement_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=80)
    scope: str = Field(default="GENERAL", min_length=1, max_length=80)
    source_reference: str = Field(min_length=1, max_length=2000)
    document_key: str = Field(default="", max_length=120)
    required: bool = True
    must_be_approved: bool = True
    max_age_days: int | None = Field(default=None, ge=1, le=36500)


class RequirementStateRequest(BaseModel):
    active: bool


class PacketAttachmentRequest(BaseModel):
    logical_name: str = Field(min_length=1, max_length=240)
    required: bool = True
    as_of: str | None = Field(default=None, max_length=10)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, (ValueError, TypeError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(
        status_code=500,
        detail=f"{type(exc).__name__}: {exc}",
    )


def _tags(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("tags must be a JSON array or comma-separated text") from exc
        if not isinstance(parsed, list):
            raise ValueError("tags JSON must be an array")
        return [str(item) for item in parsed]
    return [item.strip() for item in text.split(",") if item.strip()]


@router.get("/catalog")
def catalog(
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    return {
        "categories": sorted(CATEGORIES),
        "requirement_scopes": sorted(REQUIREMENT_SCOPES),
        "approval_policy": (
            "New file versions are candidates. Only an authorized APPROVED review "
            "promotes a version to current and supersedes the prior current version."
        ),
    }


@router.post("/documents")
async def upload_document(
    file: UploadFile = File(),
    document_key: str = Form(),
    title: str = Form(),
    category: str = Form(),
    source_reference: str = Form(),
    effective_date: str = Form(default=""),
    expires_at: str = Form(default=""),
    review_due_date: str = Form(default=""),
    description: str = Form(default=""),
    tags: str = Form(default=""),
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    try:
        filename = file.filename or ""
        content = await file.read()
        return store_document(
            document_key=document_key,
            title=title,
            category=category,
            filename=filename,
            content=content,
            source_reference=source_reference,
            actor=principal.actor,
            effective_date=effective_date,
            expires_at=expires_at,
            review_due_date=review_due_date,
            description=description,
            tags=_tags(tags),
        )
    except Exception as exc:
        raise _translate(exc) from exc
    finally:
        await file.close()


@router.get("/documents")
def documents(
    category: str | None = Query(default=None, max_length=80),
    document_key: str | None = Query(default=None, max_length=120),
    current_only: bool = Query(default=False),
    as_of: str | None = Query(default=None, max_length=10),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    try:
        return list_documents(
            category=category,
            document_key=document_key,
            current_only=current_only,
            as_of=as_of,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/documents/{document_id}")
def document(
    document_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return get_document(document_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> FileResponse:
    del principal
    try:
        metadata = get_document(document_id)
        path = resolve_document_path(document_id)
        return FileResponse(
            path=str(path),
            media_type=str(metadata["media_type"]),
            filename=str(metadata["original_filename"]),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/documents/{document_id}/review")
def review(
    document_id: str,
    payload: ReviewRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    try:
        state = payload.verification_state.strip().upper()
        if state == "APPROVED":
            return approve_document(
                document_id,
                actor=principal.actor,
                review_note=payload.review_note,
                review_due_date=payload.review_due_date,
            )
        return review_document(
            document_id,
            verification_state=state,
            actor=principal.actor,
            review_note=payload.review_note,
            review_due_date=payload.review_due_date,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/documents/{document_id}/events")
def document_events(
    document_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    try:
        return list_events(document_id, limit=limit)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/documents/{document_id}/links")
def create_link(
    document_id: str,
    payload: LinkRequest,
    principal: Principal = Depends(
        require_roles(ADMIN, GRANT_WRITER, REVIEWER)
    ),
) -> dict[str, Any]:
    try:
        return link_document(
            document_id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            purpose=payload.purpose,
            actor=principal.actor,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/documents/{document_id}/links")
def links(
    document_id: str,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    try:
        return list_links(document_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/requirements")
def create_requirement(
    payload: RequirementRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    try:
        return add_requirement(
            requirement_key=payload.requirement_key,
            title=payload.title,
            category=payload.category,
            scope=payload.scope,
            source_reference=payload.source_reference,
            actor=principal.actor,
            document_key=payload.document_key,
            required=payload.required,
            must_be_approved=payload.must_be_approved,
            max_age_days=payload.max_age_days,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/requirements")
def requirements(
    scope: str | None = Query(default=None, max_length=80),
    active_only: bool = Query(default=True),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> list[dict[str, Any]]:
    del principal
    try:
        return list_requirements(scope=scope, active_only=active_only)
    except Exception as exc:
        raise _translate(exc) from exc


@router.put("/requirements/{requirement_id}/active")
def requirement_active(
    requirement_id: str,
    payload: RequirementStateRequest,
    principal: Principal = Depends(require_roles(ADMIN, REVIEWER)),
) -> dict[str, Any]:
    try:
        return set_requirement_active(
            requirement_id,
            active=payload.active,
            actor=principal.actor,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/readiness")
def readiness(
    scope: str = Query(default="GENERAL", max_length=80),
    as_of: str | None = Query(default=None, max_length=10),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> dict[str, Any]:
    del principal
    try:
        return readiness_dashboard(scope=scope, as_of=as_of)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/packets/{packet_id}/attachments/{document_id}")
def packet_attachment(
    packet_id: str,
    document_id: str,
    payload: PacketAttachmentRequest,
    principal: Principal = Depends(require_roles(ADMIN, GRANT_WRITER)),
) -> dict[str, Any]:
    try:
        return attach_document_to_packet(
            document_id=document_id,
            packet_id=packet_id,
            logical_name=payload.logical_name,
            required=payload.required,
            actor=principal.actor,
            as_of=payload.as_of,
        )
    except Exception as exc:
        raise _translate(exc) from exc
