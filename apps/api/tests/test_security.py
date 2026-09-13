from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import app, safe_filename
from rag.security import hash_key, new_key, tenant_from_key


def test_key_is_unique_and_parseable():
    tenant = uuid4()
    first, second = new_key(tenant), new_key(tenant)
    assert first != second
    assert tenant_from_key(first) == tenant
    assert len(hash_key(first)) == 64
    assert hash_key(first) != hash_key(second)


@pytest.mark.parametrize("key", ["", "bad", "rag_invalid_secret", f"rag_{uuid4().hex}_short"])
def test_invalid_keys(key):
    with pytest.raises(HTTPException) as error:
        tenant_from_key(key)
    assert error.value.status_code == 401


def test_protected_routes_reject_missing_credentials_without_database():
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    response = client.get("/v1/knowledge-bases")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_schema_rejects_client_tenant_override():
    from pydantic import ValidationError

    from app import KnowledgeBaseInput

    with pytest.raises(ValidationError):
        KnowledgeBaseInput(name="Example", tenant_id=str(uuid4()))


def test_safe_filename_removes_path_and_unsafe_characters():
    assert safe_filename("../folder/report?.md") == "report_.md"


@pytest.mark.parametrize(
    "method,path",
    [
        ("delete", "/v1/documents/{id}"),
        ("post", "/v1/documents/{id}/reindex"),
        ("delete", "/v1/chatbots/{id}"),
    ],
)
def test_document_and_chatbot_routes_require_credentials(method, path):
    # These destroy or re-run work, so an unauthenticated call must never reach
    # the database to find out whether the id exists.
    client = TestClient(app)
    response = getattr(client, method)(path.format(id=uuid4()))
    assert response.status_code == 401
