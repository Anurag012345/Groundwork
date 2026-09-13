import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Connection, text

from rag.db import assert_runtime_role, engine, set_tenant

bearer = HTTPBearer(auto_error=False)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key(tenant_id: UUID) -> str:
    return f"rag_{tenant_id.hex}_{secrets.token_urlsafe(32)}"


def tenant_from_key(key: str) -> UUID:
    try:
        prefix, tenant, secret = key.split("_", 2)
        if prefix != "rag" or len(secret) < 40:
            raise ValueError
        return UUID(hex=tenant)
    except ValueError:
        raise HTTPException(401, "Invalid API key") from None


@dataclass
class TenantSession:
    tenant_id: UUID
    connection: Connection


def tenant_session(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None:
        raise HTTPException(401, "API key required")
    key = credentials.credentials
    tenant_id = tenant_from_key(key)
    with engine().begin() as connection:
        assert_runtime_role(connection)
        set_tenant(connection, tenant_id)
        # Tenant in the key is only a lookup hint. The full hash MUST match before access.
        valid = connection.execute(
            text("SELECT id FROM api_keys WHERE key_hash=:hash AND revoked_at IS NULL"),
            {"hash": hash_key(key)},
        ).scalar_one_or_none()
        if valid is None:
            raise HTTPException(401, "Invalid API key")
        yield TenantSession(tenant_id, connection)


SessionDependency = Annotated[TenantSession, Depends(tenant_session, scope="function")]
