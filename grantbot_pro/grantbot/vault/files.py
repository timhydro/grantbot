from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
import zipfile
from pathlib import Path
from typing import Any


MAX_DEFAULT_BYTES = 50 * 1024 * 1024
MAX_ALLOWED_BYTES = 200 * 1024 * 1024
MAX_ZIP_ENTRIES = 2500
MAX_ZIP_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
MAX_ZIP_RATIO = 1000.0

MEDIA_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
}


def vault_root() -> Path:
    configured = os.getenv("GRANTBOT_VAULT_ROOT", "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        root = Path(__file__).resolve().parents[2] / "data" / "document_vault"
    root.mkdir(parents=True, exist_ok=True)
    (root / "objects").mkdir(parents=True, exist_ok=True)
    return root


def max_bytes() -> int:
    raw = os.getenv("GRANTBOT_VAULT_MAX_BYTES", str(MAX_DEFAULT_BYTES)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("GRANTBOT_VAULT_MAX_BYTES must be an integer") from exc
    if value <= 0 or value > MAX_ALLOWED_BYTES:
        raise ValueError(
            f"GRANTBOT_VAULT_MAX_BYTES must be between 1 and {MAX_ALLOWED_BYTES}"
        )
    return value


def safe_filename(value: Any) -> str:
    name = Path(str(value or "")).name.strip()
    if not name or name in {".", ".."} or "\x00" in name:
        raise ValueError("A valid filename is required")
    if len(name) > 240:
        raise ValueError("filename is too long")
    extension = Path(name).suffix.lower()
    if extension not in MEDIA_BY_EXTENSION:
        raise ValueError(
            "Unsupported file extension. Allowed: "
            + ", ".join(sorted(MEDIA_BY_EXTENSION))
        )
    return name


def _zip_media(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise ValueError("OOXML archive contains too many entries")
            total_uncompressed = sum(max(0, int(info.file_size)) for info in infos)
            total_compressed = sum(max(0, int(info.compress_size)) for info in infos)
            if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ValueError("OOXML archive expands beyond the safety limit")
            ratio = total_uncompressed / max(total_compressed, 1)
            if ratio > MAX_ZIP_RATIO:
                raise ValueError("OOXML archive compression ratio exceeds safety limit")
            names = set(archive.namelist())
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid ZIP/OOXML document") from exc
    if "word/document.xml" in names:
        return MEDIA_BY_EXTENSION[".docx"]
    if "xl/workbook.xml" in names:
        return MEDIA_BY_EXTENSION[".xlsx"]
    if "ppt/presentation.xml" in names:
        return MEDIA_BY_EXTENSION[".pptx"]
    return "application/zip"


def detect_media(content: bytes, filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"PK\x03\x04"):
        return _zip_media(content)
    if b"\x00" not in content[:262144]:
        try:
            text = content[:262144].decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if text or content == b"":
            if extension == ".json":
                try:
                    json.loads(content.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("Invalid JSON document") from exc
                return "application/json"
            if extension == ".csv":
                return "text/csv"
            if extension == ".md":
                return "text/markdown"
            return "text/plain"
    return "application/octet-stream"


def validate_content(content: bytes, filename: str) -> tuple[str, str, str]:
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if not content:
        raise ValueError("Document cannot be empty")
    if len(content) > max_bytes():
        raise ValueError("Document exceeds configured vault size limit")
    name = safe_filename(filename)
    expected = MEDIA_BY_EXTENSION[Path(name).suffix.lower()]
    detected = detect_media(content, name)
    if detected != expected:
        raise ValueError(
            f"File content does not match extension: detected {detected}, expected {expected}"
        )
    sha256 = hashlib.sha256(content).hexdigest()
    return name, detected, sha256


def object_path(sha256: str) -> tuple[Path, str]:
    if not len(sha256) == 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise ValueError("Invalid SHA-256 digest")
    relative = Path("objects") / sha256[:2] / sha256
    root = vault_root().resolve()
    absolute = (root / relative).resolve()
    if root not in absolute.parents:
        raise RuntimeError("Vault object path escaped controlled root")
    return absolute, relative.as_posix()


def write_object(content: bytes, sha256: str) -> str:
    destination, relative = object_path(sha256)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing_sha = hashlib.sha256(destination.read_bytes()).hexdigest()
        if existing_sha != sha256:
            raise RuntimeError("Existing vault object failed hash verification")
        return relative
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return relative


def resolve_object(relative_path: str, expected_sha256: str) -> Path:
    root = vault_root().resolve()
    candidate = (root / relative_path).resolve()
    if root not in candidate.parents:
        raise RuntimeError("Stored vault path escaped controlled root")
    if not candidate.is_file():
        raise FileNotFoundError("Vault object is missing")
    actual_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError("Vault object hash verification failed")
    return candidate
