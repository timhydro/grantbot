from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from grantbot.core.config import settings
from grantbot.core.database import connection, utc_now


ADMIN = "ADMIN"
GRANT_WRITER = "GRANT_WRITER"
REVIEWER = "REVIEWER"
FINANCIAL_REVIEWER = "FINANCIAL_REVIEWER"
AUTHORIZED_REPRESENTATIVE = "AUTHORIZED_REPRESENTATIVE"

ROLES = {
    ADMIN,
    GRANT_WRITER,
    REVIEWER,
    FINANCIAL_REVIEWER,
    AUTHORIZED_REPRESENTATIVE,
}

PBKDF2_ITERATIONS = 240_000
KEY_PATTERN = re.compile(r"^gbk_([0-9a-f]{16})_([A-Za-z0-9_-]{20,128})$")
API_KEY_HEADER = APIKeyHeader(name="X-GrantBot-Key", auto_error=False)


@dataclass(frozen=True, slots=True)
class Principal:
    key_id: str
    label: str
    role: str

    @property
    def actor(self) -> str:
        return f"{self.label}<{self.role}:{self.key_id}>"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _key_file() -> Path:
    configured = os.getenv("GRANTBOT_MASTER_API_KEY_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (settings.data_dir / "master_api_key.txt").resolve()


def initialize_security_schema() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS auth_keys_v20 (
                key_id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                role TEXT NOT NULL,
                salt_hex TEXT NOT NULL,
                key_hash_hex TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL DEFAULT '',
                revoked_at TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_auth_keys_v20_role_active
                ON auth_keys_v20(role, active);
            """
        )


def _normalize_role(role: str) -> str:
    normalized = str(role).strip().upper()
    if normalized not in ROLES:
        raise ValueError(
            f"Invalid role {normalized!r}. Allowed roles: {', '.join(sorted(ROLES))}"
        )
    return normalized


def _parse_key(api_key: str) -> tuple[str, str]:
    match = KEY_PATTERN.fullmatch(str(api_key or "").strip())
    if match is None:
        raise ValueError("Invalid GrantBot API key format")
    return match.group(1), match.group(2)


def _derive(secret: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    ).hex()


def _insert_key(
    *,
    key_id: str,
    secret: str,
    label: str,
    role: str,
) -> None:
    role = _normalize_role(role)
    label = label.strip()
    if not label:
        raise ValueError("Key label is required")
    if not re.fullmatch(r"[0-9a-f]{16}", key_id):
        raise ValueError("Invalid key_id")
    salt = secrets.token_bytes(32)
    created_at = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_keys_v20(
                key_id, label, role, salt_hex, key_hash_hex,
                active, created_at, last_used_at, revoked_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, '', '')
            """,
            (
                key_id,
                label,
                role,
                salt.hex(),
                _derive(secret, salt),
                created_at,
            ),
        )


def create_api_key(*, label: str, role: str) -> dict[str, Any]:
    initialize_security_schema()
    role = _normalize_role(role)
    label = label.strip()
    if not label:
        raise ValueError("Key label is required")
    for _ in range(20):
        key_id = secrets.token_hex(8)
        with connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM auth_keys_v20 WHERE key_id=?",
                (key_id,),
            ).fetchone()
        if exists is None:
            break
    else:
        raise RuntimeError("Unable to generate a unique API key identifier")
    secret = secrets.token_urlsafe(32)
    _insert_key(key_id=key_id, secret=secret, label=label, role=role)
    api_key = f"gbk_{key_id}_{secret}"
    return {
        "key_id": key_id,
        "label": label,
        "role": role,
        "api_key": api_key,
        "created_at": utc_now(),
        "warning": "Store this API key securely. It cannot be recovered from the database.",
    }


def authenticate_api_key(api_key: str, *, touch: bool = True) -> Principal:
    initialize_security_schema()
    key_id, secret = _parse_key(api_key)
    with connection() as conn:
        row = conn.execute(
            """
            SELECT key_id, label, role, salt_hex, key_hash_hex, active
            FROM auth_keys_v20
            WHERE key_id=?
            """,
            (key_id,),
        ).fetchone()
        if row is None or not bool(row["active"]):
            raise PermissionError("Unknown or revoked GrantBot API key")
        try:
            salt = bytes.fromhex(str(row["salt_hex"]))
        except ValueError as exc:
            raise PermissionError("Stored GrantBot key metadata is invalid") from exc
        candidate = _derive(secret, salt)
        if not hmac.compare_digest(candidate, str(row["key_hash_hex"])):
            raise PermissionError("Invalid GrantBot API key")
        if touch:
            conn.execute(
                "UPDATE auth_keys_v20 SET last_used_at=? WHERE key_id=?",
                (utc_now(), key_id),
            )
    return Principal(
        key_id=str(row["key_id"]),
        label=str(row["label"]),
        role=str(row["role"]),
    )


def list_api_keys() -> list[dict[str, Any]]:
    initialize_security_schema()
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT key_id, label, role, active, created_at, last_used_at, revoked_at
            FROM auth_keys_v20
            ORDER BY active DESC, role, label, created_at
            """
        ).fetchall()
    return [
        {
            "key_id": str(row["key_id"]),
            "label": str(row["label"]),
            "role": str(row["role"]),
            "active": bool(row["active"]),
            "created_at": str(row["created_at"]),
            "last_used_at": str(row["last_used_at"]),
            "revoked_at": str(row["revoked_at"]),
        }
        for row in rows
    ]


def revoke_api_key(key_id: str, *, actor: Principal) -> dict[str, Any]:
    initialize_security_schema()
    if actor.role != ADMIN:
        raise PermissionError("Only ADMIN may revoke API keys")
    key_id = key_id.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{16}", key_id):
        raise ValueError("Invalid key_id")
    with connection() as conn:
        row = conn.execute(
            "SELECT key_id, label, role, active FROM auth_keys_v20 WHERE key_id=?",
            (key_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"API key not found: {key_id}")
        if not bool(row["active"]):
            return {
                "key_id": key_id,
                "label": str(row["label"]),
                "role": str(row["role"]),
                "active": False,
                "already_revoked": True,
            }
        if str(row["role"]) == ADMIN:
            admin_count = conn.execute(
                "SELECT COUNT(*) AS count FROM auth_keys_v20 WHERE role=? AND active=1",
                (ADMIN,),
            ).fetchone()
            if int(admin_count["count"]) <= 1:
                raise ValueError("Cannot revoke the last active ADMIN key")
        revoked_at = utc_now()
        conn.execute(
            "UPDATE auth_keys_v20 SET active=0, revoked_at=? WHERE key_id=?",
            (revoked_at, key_id),
        )
    return {
        "key_id": key_id,
        "label": str(row["label"]),
        "role": str(row["role"]),
        "active": False,
        "revoked_at": revoked_at,
    }


def _restore_key_file_record(raw_key: str) -> Principal | None:
    try:
        key_id, secret = _parse_key(raw_key)
    except ValueError:
        return None
    with connection() as conn:
        row = conn.execute(
            "SELECT key_id, role, active FROM auth_keys_v20 WHERE key_id=?",
            (key_id,),
        ).fetchone()
    if row is not None:
        try:
            principal = authenticate_api_key(raw_key, touch=False)
        except (ValueError, PermissionError):
            return None
        return principal if principal.role == ADMIN else None
    _insert_key(
        key_id=key_id,
        secret=secret,
        label="local-admin",
        role=ADMIN,
    )
    return authenticate_api_key(raw_key, touch=False)


def ensure_admin_key() -> dict[str, Any]:
    initialize_security_schema()
    key_file = _key_file()
    key_file.parent.mkdir(parents=True, exist_ok=True)

    if key_file.is_file():
        raw = key_file.read_text(encoding="utf-8").strip()
        principal = _restore_key_file_record(raw)
        if principal is not None:
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass
            return {
                "created": False,
                "key_file": str(key_file),
                "principal": principal.to_dict(),
            }

    generated = create_api_key(label="local-admin", role=ADMIN)
    raw_key = str(generated["api_key"])
    temporary = key_file.with_name(f".{key_file.name}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(raw_key + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, key_file)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return {
        "created": True,
        "key_file": str(key_file),
        "principal": {
            "key_id": generated["key_id"],
            "label": generated["label"],
            "role": generated["role"],
        },
    }


def security_status() -> dict[str, Any]:
    initialize_security_schema()
    keys = list_api_keys()
    active = [item for item in keys if item["active"]]
    counts: dict[str, int] = {role: 0 for role in sorted(ROLES)}
    for item in active:
        counts[item["role"]] = counts.get(item["role"], 0) + 1
    key_file = _key_file()
    return {
        "enabled": True,
        "header": "X-GrantBot-Key",
        "active_key_count": len(active),
        "active_roles": counts,
        "admin_key_file_exists": key_file.is_file(),
        "admin_key_file": str(key_file),
        "pbkdf2_iterations": PBKDF2_ITERATIONS,
    }


def require_roles(
    *roles: str,
) -> Callable[..., Coroutine[Any, Any, Principal]]:
    allowed = {_normalize_role(role) for role in roles} if roles else set(ROLES)

    async def dependency(
        api_key: str | None = Security(API_KEY_HEADER),
    ) -> Principal:
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-GrantBot-Key is required",
            )
        try:
            principal = authenticate_api_key(api_key)
        except (ValueError, PermissionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked GrantBot API key",
            ) from exc
        if principal.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role {principal.role} is not authorized for this action. "
                    f"Allowed roles: {', '.join(sorted(allowed))}"
                ),
            )
        return principal

    return dependency
