"""Controlled, versioned organizational document vault for GrantBot."""

from grantbot.vault.service import (
    add_requirement,
    approve_document,
    attach_document_to_packet,
    document_freshness,
    get_document,
    list_documents,
    list_links,
    list_requirements,
    link_document,
    readiness_dashboard,
    resolve_document_path,
    review_document,
    store_document,
)

__all__ = [
    "add_requirement",
    "approve_document",
    "attach_document_to_packet",
    "document_freshness",
    "get_document",
    "list_documents",
    "list_links",
    "list_requirements",
    "link_document",
    "readiness_dashboard",
    "resolve_document_path",
    "review_document",
    "store_document",
]
