"""Users and sessions against a real migrated PostgreSQL. Never point this at production data.

Set TEST_ADMIN_DATABASE_URL (migration role) and TEST_DATABASE_URL (restricted runtime role).
"""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

import app as api
from rag import accounts, security
from rag.db import assert_runtime_role, set_tenant

pytestmark = pytest.mark.integration
PASSWORD = "correct horse battery"


@pytest.fixture
def database(monkeypatch):
    admin_url = os.environ.get("TEST_ADMIN_DATABASE_URL")
    runtime_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url or not runtime_url:
        pytest.skip("Set TEST_ADMIN_DATABASE_URL and TEST_DATABASE_URL for PostgreSQL tests")
    admin, runtime = create_engine(admin_url), create_engine(runtime_url)
    # The API and the accounts code both connect through engine(); point them at the test database.
    monkeypatch.setattr(accounts, "engine", lambda: runtime)
    monkeypatch.setattr(security, "engine", lambda: runtime)
    api._asked.clear()
    tenants = []

    def workspace(name):
        tenant, email = uuid4(), f"{uuid4().hex[:10]}@test.example"
        with admin.begin() as conn:
            set_tenant(conn, tenant)
            conn.execute(text("INSERT INTO tenants(id, name) VALUES (:id, :name)"), {"id": tenant, "name": name})
            accounts.create_user(conn, tenant, email, PASSWORD)
        tenants.append(tenant)
        return tenant, email

    yield admin, runtime, workspace
    with admin.begin() as conn:
        for tenant in tenants:
            set_tenant(conn, tenant)
            conn.execute(text("DELETE FROM tenants WHERE id=:id"), {"id": tenant})
    admin.dispose()
    runtime.dispose()


def me(client, token):
    return client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})


def test_the_runtime_role_is_still_considered_safe_with_the_new_tables(database):
    _, runtime, _ = database
    with runtime.connect() as conn:
        assert_runtime_role(conn)


def test_login_session_logout_cycle(database):
    _, _, workspace = database
    tenant, email = workspace("Acme")
    client = TestClient(api.app)
    login = client.post("/v1/auth/login", json={"email": email.upper(), "password": PASSWORD})
    assert login.status_code == 200
    token = login.json()["token"]
    assert login.json()["tenant"] == {"id": str(tenant), "name": "Acme"}
    assert me(client, token).json() == {"id": str(tenant), "name": "Acme"}
    assert client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 204
    assert me(client, token).status_code == 401


def test_wrong_password_and_unknown_email_are_the_same_401(database):
    _, _, workspace = database
    _, email = workspace("Acme")
    client = TestClient(api.app)
    wrong = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD + "x"})
    unknown = client.post("/v1/auth/login", json={"email": "nobody@test.example", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_disabling_a_user_ends_their_session_and_blocks_login(database):
    admin, _, workspace = database
    _, email = workspace("Acme")
    client = TestClient(api.app)
    token = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    assert me(client, token).status_code == 200
    with admin.begin() as conn:
        accounts.disable_user(conn, email)
    assert me(client, token).status_code == 401
    assert client.post("/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401


def test_changing_a_password_signs_the_user_out_everywhere(database):
    admin, _, workspace = database
    _, email = workspace("Acme")
    client = TestClient(api.app)
    token = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    with admin.begin() as conn:
        accounts.set_password(conn, email, "a brand new passphrase")
    assert me(client, token).status_code == 401
    assert client.post("/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert client.post(
        "/v1/auth/login", json={"email": email, "password": "a brand new passphrase"}
    ).status_code == 200


def test_an_expired_session_is_refused(database):
    admin, _, workspace = database
    tenant, email = workspace("Acme")
    client = TestClient(api.app)
    token = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    with admin.begin() as conn:
        set_tenant(conn, tenant)
        conn.execute(text("UPDATE user_sessions SET expires_at = now() - interval '1 minute'"))
    assert me(client, token).status_code == 401


def test_a_session_cannot_be_used_against_another_workspace(database):
    _, _, workspace = database
    _, email = workspace("Acme")
    other, _ = workspace("Other")
    client = TestClient(api.app)
    token = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    forged = f"rags_{other.hex}_{token.split('_', 2)[2]}"
    assert me(client, forged).status_code == 401


def test_row_security_and_grants_on_users_and_sessions(database):
    admin, runtime, workspace = database
    a, email_a = workspace("A")
    b, _ = workspace("B")
    client = TestClient(api.app)
    assert client.post("/v1/auth/login", json={"email": email_a, "password": PASSWORD}).status_code == 200
    with runtime.begin() as conn:
        set_tenant(conn, b)
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 1  # only B's own user
        assert conn.execute(text("SELECT count(*) FROM user_sessions")).scalar() == 0  # A's is hidden
        # The one lookup that crosses tenants answers an exact email and nothing broader.
        found = conn.execute(text("SELECT tenant_id FROM find_login(:e)"), {"e": email_a}).scalars().all()
        assert found == [a]
        assert conn.execute(text("SELECT count(*) FROM find_login('')")).scalar() == 0
    with pytest.raises(DBAPIError), runtime.begin() as conn:
        set_tenant(conn, a)
        conn.execute(text("UPDATE users SET password_hash='x'"))
    with pytest.raises(DBAPIError), runtime.begin() as conn:
        set_tenant(conn, a)
        conn.execute(
            text("INSERT INTO users(id, tenant_id, email, password_hash) VALUES (:id, :t, 'x@y.zz', 'x')"),
            {"id": uuid4(), "t": a},
        )
    with pytest.raises(DBAPIError), runtime.begin() as conn:
        set_tenant(conn, b)
        conn.execute(
            text("INSERT INTO user_sessions(token_hash, tenant_id, user_id, expires_at) "
                 "VALUES (repeat('a', 64), :t, :u, now())"),
            {"t": b, "u": uuid4()},
        )
    with admin.begin() as conn:  # the migration role is the only one that may create accounts
        assert conn.execute(text("SELECT count(*) FROM users WHERE tenant_id=:t"), {"t": a}).scalar() == 1
