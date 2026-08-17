from __future__ import annotations

from pathlib import Path
from typing import Any

from grantbot.vault.repository import (
    clean,
    document_freshness,
    get_document,
    link_document,
    resolve_document_path,
)


def attach_document_to_packet(
    *,
    document_id: str,
    packet_id: str,
    logical_name: str,
    required: bool,
    actor: str,
    as_of: str | None = None,
) -> dict[str, Any]:
    document = get_document(document_id)
    freshness = document_freshness(document, as_of=as_of)
    if not freshness["usable_for_packet"]:
        raise ValueError(
            "Vault document is not eligible for packet attachment: "
            f"freshness={freshness['state']}, "
            f"verification={document['verification_state']}"
        )
    actor = clean(actor, max_length=500)
    packet_id = clean(packet_id, max_length=120)
    logical_name = Path(str(logical_name or "")).name.strip()
    if not actor or not packet_id or not logical_name:
        raise ValueError("actor, packet_id, and logical_name are required")
    path = resolve_document_path(document_id)

    from grantbot.packaging.packet_guard_v19 import (
        register_attachment,
        verify_attachment,
    )

    packet = register_attachment(
        packet_id,
        source_path=str(path),
        logical_name=logical_name,
        required=required,
        media_type=str(document["media_type"]),
    )
    match = next(
        (
            item
            for item in packet.get("attachments", [])
            if str(item.get("logical_name", "")).casefold()
            == logical_name.casefold()
        ),
        None,
    )
    if match is None:
        raise RuntimeError(
            "Packet attachment was registered but could not be resolved"
        )
    verified_packet = verify_attachment(
        packet_id,
        str(match["attachment_id"]),
        actor=actor,
    )
    link = link_document(
        document_id,
        entity_type="APPLICATION_PACKET",
        entity_id=packet_id,
        purpose=f"attachment:{logical_name}",
        actor=actor,
    )
    return {
        "document": document,
        "freshness": freshness,
        "attachment_id": str(match["attachment_id"]),
        "link": link,
        "packet": verified_packet,
    }
