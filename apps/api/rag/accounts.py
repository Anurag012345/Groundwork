"""Dashboard accounts: password hashing, email and password login, and the administrator calls
behind `python -m rag.users`. Every user of a workspace has the same access as its API key."""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from functools import cache
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from rag.config import settings
from rag.db import assert_runtime_role, engine, set_tenant
from rag.security import hash_key, new_session_token

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1  # about 16 MiB and tens of milliseconds per check
SCRYPT_MAXMEM = 2**26  # hashlib's default limit is below what these parameters need
MIN_PASSWORD = 12
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=SCRYPT_MAXMEM,
        )
        return scheme == "scrypt" and hmac.compare_digest(candidate, bytes.fromhex(digest))
    except ValueError:  # a malformed or unsupported hash never verifies
        return False


@cache
def decoy_hash() -> str:
    """Checked when the email is unknown, so a miss costs as much time as a wrong password."""
    return hash_password(secrets.token_urlsafe(16))


def authenticate(email: str, password: str) -> dict | None:
    """Verify the password and open a session. None for any failure, without saying which."""
    with engine().begin() as connection:
        assert_runtime_role(connection)
        found = (
            connection.execute(text("SELECT * FROM find_login(:email)"), {"email": email.strip()})
            .mappings()
            .one_or_none()
        )
        correct = verify_password(password, found["password_hash"] if found else decoy_hash())
        if not (found and correct):
            return None
        tenant_id = found["tenant_id"]
        set_tenant(connection, tenant_id)
        token = new_session_token(tenant_id)
        expires_at = datetime.now(UTC) + timedelta(hours=settings().session_hours)
        connection.execute(
            text("""
                INSERT INTO user_sessions(token_hash, tenant_id, user_id, expires_at)
                VALUES (:hash, :tenant, :user, :expires)
            """),
            {"hash": hash_key(token), "tenant": tenant_id, "user": found["user_id"], "expires": expires_at},
        )
        # Expired rows are only ever dead weight; the tenant's own are cleared on each login.
        connection.execute(text("DELETE FROM user_sessions WHERE expires_at < now()"))
        name = connection.execute(text("SELECT name FROM tenants WHERE id=:id"), {"id": tenant_id}).scalar_one()
    return {
        "token": token,
        "expires_at": expires_at,
        "tenant": {"id": tenant_id, "name": name},
    }


def check_new_credentials(email: str, password: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL.match(email):
        raise ValueError("That does not look like an email address")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"The password must have at least {MIN_PASSWORD} characters")
    return email


def create_user(connection: Connection, tenant_id: UUID, email: str, password: str) -> UUID:
    """Administrator call: the connection is the migration role's, not the API's."""
    email = check_new_credentials(email, password)
    set_tenant(connection, tenant_id)
    user_id = uuid4()
    connection.execute(
        text("INSERT INTO users(id, tenant_id, email, password_hash) VALUES (:id, :tenant, :email, :hash)"),
        {"id": user_id, "tenant": tenant_id, "email": email, "hash": hash_password(password)},
    )
    return user_id


def _locate(connection: Connection, email: str):
    found = connection.execute(
        text("SELECT user_id, tenant_id FROM find_login(:email)"), {"email": email.strip()}
    ).one_or_none()
    if found is None:
        raise ValueError("No enabled user has that email")
    set_tenant(connection, found.tenant_id)
    return found


def set_password(connection: Connection, email: str, password: str) -> None:
    check_new_credentials(email, password)
    found = _locate(connection, email)
    connection.execute(
        text("UPDATE users SET password_hash=:hash WHERE id=:id"),
        {"hash": hash_password(password), "id": found.user_id},
    )
    connection.execute(text("DELETE FROM user_sessions WHERE user_id=:id"), {"id": found.user_id})


def disable_user(connection: Connection, email: str) -> None:
    found = _locate(connection, email)
    connection.execute(text("UPDATE users SET disabled_at=now() WHERE id=:id"), {"id": found.user_id})
    connection.execute(text("DELETE FROM user_sessions WHERE user_id=:id"), {"id": found.user_id})
