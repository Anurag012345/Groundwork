import hashlib
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Connection, text

from rag.db import assert_runtime_role, engine, set_tenant

bearer = HTTPBearer(auto_error=False)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key(tenant_id: UUID) -> str:
    return f"rag_{tenant_id.hex}_{secrets.token_urlsafe(32)}"


def new_public_key(tenant_id: UUID) -> str:
    # Not a secret: this ships in the host page's source. Stored in plaintext so the
    # dashboard can show the embed snippet. Access is bounded by the origin allowlist
    # and by the chatbot row, which permits asking questions and nothing else.
    return f"ragpub_{tenant_id.hex}_{secrets.token_urlsafe(24)}"


def new_session_token(tenant_id: UUID) -> str:
    # "rags" has no underscore, so it cannot be mistaken for the "rag" of an API key.
    return f"rags_{tenant_id.hex}_{secrets.token_urlsafe(32)}"


def _tenant_hint(key: str, prefix: str, minimum: int) -> UUID:
    try:
        found, tenant, secret = key.split("_", 2)
        if found != prefix or len(secret) < minimum:
            raise ValueError
        return UUID(hex=tenant)
    except ValueError:
        raise HTTPException(401, "Invalid credentials") from None


def tenant_from_key(key: str) -> UUID:
    return _tenant_hint(key, "rag", 40)


def tenant_from_public_key(key: str) -> UUID:
    return _tenant_hint(key, "ragpub", 30)


def tenant_from_session_token(token: str) -> UUID:
    return _tenant_hint(token, "rags", 40)


@dataclass
class TenantSession:
    tenant_id: UUID
    connection: Connection
    # Set when the caller signed in with a password, so that logout can end this session only.
    session_hash: str | None = None


def tenant_session(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None:
        raise HTTPException(401, "API key or session required")
    key = credentials.credentials
    signed_in = key.startswith("rags_")
    tenant_id = tenant_from_session_token(key) if signed_in else tenant_from_key(key)
    with engine().begin() as connection:
        assert_runtime_role(connection)
        set_tenant(connection, tenant_id)
        # Tenant in the key is only a lookup hint. The full hash MUST match before access.
        if signed_in:
            valid = connection.execute(
                text("""
                    SELECT s.user_id FROM user_sessions s
                    JOIN users u ON u.id = s.user_id AND u.tenant_id = s.tenant_id
                    WHERE s.token_hash=:hash AND s.expires_at > now() AND u.disabled_at IS NULL
                """),
                {"hash": hash_key(key)},
            ).scalar_one_or_none()
        else:
            valid = connection.execute(
                text("SELECT id FROM api_keys WHERE key_hash=:hash AND revoked_at IS NULL"),
                {"hash": hash_key(key)},
            ).scalar_one_or_none()
        if valid is None:
            raise HTTPException(401, "Invalid or expired credentials")
        yield TenantSession(tenant_id, connection, hash_key(key) if signed_in else None)


SessionDependency = Annotated[TenantSession, Depends(tenant_session, scope="function")]


@dataclass
class WidgetSession:
    tenant_id: UUID
    chatbot: Mapping
    connection: Connection


def origin_allowed(origin: str | None, allowed: Sequence[str]) -> bool:
    # Fails closed: a chatbot with no configured origins answers nowhere, and a
    # request carrying no Origin at all is not a browser on an allowed site.
    return bool(origin) and origin in allowed


def widget_session(public_key: str, origin: Annotated[str | None, Header()] = None):
    tenant_id = tenant_from_public_key(public_key)
    with engine().begin() as connection:
        assert_runtime_role(connection)
        set_tenant(connection, tenant_id)
        chatbot = (
            connection.execute(
                text("""
                    SELECT id, knowledge_base_id, name, greeting, allowed_origins
                    FROM chatbots WHERE public_key=:key
                """),
                {"key": public_key},
            )
            .mappings()
            .one_or_none()
        )
        if chatbot is None:
            raise HTTPException(404, "Chatbot not found")
        if not origin_allowed(origin, chatbot["allowed_origins"]):
            raise HTTPException(403, "This chatbot is not enabled for this website")
        yield WidgetSession(tenant_id, chatbot, connection)


WidgetDependency = Annotated[WidgetSession, Depends(widget_session, scope="function")]
