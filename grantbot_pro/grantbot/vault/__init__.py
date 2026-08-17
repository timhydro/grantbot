"""Controlled, versioned organizational document vault for GrantBot."""

from grantbot.vault.packet import attach_document_to_packet
from grantbot.vault.readiness import readiness_dashboard
from grantbot.vault.repository import (
    add_requirement,
    approve_document,
    document_freshness,
    get_document,
    list_documents,
    list_events,
    list_links,
    list_requirements,
    link_document,
    resolve_document_path,
    review_document,
    set_requirement_active,
    store_document,
)

__all__ = [
    "add_requirement",
    "approve_document",
    "attach_document_to_packet",
    "document_freshness",
    "get_document",
    "list_documents",
    "list_events",
    "list_links",
    "list_requirements",
    "link_document",
    "readiness_dashboard",
    "resolve_document_path",
    "review_document",
    "set_requirement_active",
    "store_document",
]
