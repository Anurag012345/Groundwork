from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as api
from rag.accounts import (
    MIN_PASSWORD,
    check_new_credentials,
    decoy_hash,
    hash_password,
    verify_password,
)
from rag.security import (
    new_key,
    new_public_key,
    new_session_token,
    tenant_from_key,
    tenant_from_public_key,
    tenant_from_session_token,
)

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def clear_rate_limit():
    api._asked.clear()
    yield
    api._asked.clear()


def test_password_round_trip_and_wrong_password():
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt$")
    assert verify_password(PASSWORD, stored)
    assert not verify_password(PASSWORD + "x", stored)
    assert not verify_password("", stored)


def test_two_hashes_of_one_password_differ():
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


@pytest.mark.parametrize(
    "stored", ["", "plain", "scrypt$1$2", "bcrypt$16384$8$1$00$00", "scrypt$x$8$1$00$00", "scrypt$16384$8$1$zz$00"]
)
def test_a_malformed_stored_hash_never_verifies(stored):
    assert verify_password(PASSWORD, stored) is False


def test_decoy_hash_is_a_real_hash_that_nobody_knows():
    assert decoy_hash() == decoy_hash()
    assert verify_password("anything", decoy_hash()) is False


def test_new_credentials_are_checked_and_the_email_is_lowercased():
    assert check_new_credentials("  Pat@Client.Example ", PASSWORD) == "pat@client.example"
    for bad in ("", "no-at-sign", "a@b", "two words@x.com"):
        with pytest.raises(ValueError):
            check_new_credentials(bad, PASSWORD)
    with pytest.raises(ValueError):
        check_new_credentials("pat@client.example", "x" * (MIN_PASSWORD - 1))


def test_session_tokens_round_trip_and_are_not_interchangeable_with_keys():
    tenant = uuid4()
    token = new_session_token(tenant)
    assert token.startswith("rags_")
    assert tenant_from_session_token(token) == tenant
    assert new_session_token(tenant) != token
    # A session must not pass for an API key, a widget key, or the other way round.
    for other in (tenant_from_key, tenant_from_public_key):
        with pytest.raises(HTTPException):
            other(token)
    for key in (new_key(tenant), new_public_key(tenant)):
        with pytest.raises(HTTPException):
            tenant_from_session_token(key)


def test_login_returns_the_session_and_passes_the_credentials_through(monkeypatch):
    seen = {}

    def fake(email, password):
        seen.update(email=email, password=password)
        return {"token": "rags_x", "expires_at": datetime.now(UTC), "tenant": {"id": str(uuid4()), "name": "Acme"}}

    monkeypatch.setattr(api, "authenticate", fake)
    response = TestClient(api.app).post("/v1/auth/login", json={"email": "pat@client.example", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["token"] == "rags_x"
    assert response.headers["cache-control"] == "no-store"
    assert seen == {"email": "pat@client.example", "password": PASSWORD}


def test_a_failed_login_is_401_with_one_message(monkeypatch):
    monkeypatch.setattr(api, "authenticate", lambda email, password: None)
    response = TestClient(api.app).post("/v1/auth/login", json={"email": "a@b.co", "password": "nope"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Wrong email or password"}


def test_login_is_rate_limited_per_email(monkeypatch):
    monkeypatch.setattr(api, "authenticate", lambda email, password: None)
    client = TestClient(api.app)
    codes = [
        client.post("/v1/auth/login", json={"email": "Target@b.co", "password": "guess"}).status_code
        for _ in range(7)
    ]
    assert codes == [401] * 5 + [429] * 2
    # The limit follows the address, not the capitalisation, and spares other accounts.
    assert client.post("/v1/auth/login", json={"email": "other@b.co", "password": "x"}).status_code == 401


def test_login_rejects_unknown_fields_and_logout_needs_a_session():
    client = TestClient(api.app)
    assert client.post("/v1/auth/login", json={"email": "a@b.co", "password": "x", "tenant_id": "1"}).status_code == 422
    assert client.post("/v1/auth/logout").status_code == 401
