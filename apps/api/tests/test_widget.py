from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app as api
from app import ChatbotInput, QuestionInput, check_origin_format, rate_limit
from rag.security import (
    new_key,
    new_public_key,
    origin_allowed,
    tenant_from_key,
    tenant_from_public_key,
)

WIDGET = "/public/v1/chatbots/ragpub_{}_{}".format(uuid4().hex, "x" * 30)


@pytest.fixture(autouse=True)
def clear_rate_limit():
    api._asked.clear()
    yield
    api._asked.clear()


def test_public_key_round_trips_and_is_unique():
    tenant = uuid4()
    first, second = new_public_key(tenant), new_public_key(tenant)
    assert first != second
    assert tenant_from_public_key(first) == tenant


def test_public_and_private_keys_are_not_interchangeable():
    tenant = uuid4()
    # A tenant's administrative key must never be usable as a widget key: it would
    # put a credential that can delete knowledge bases into a public web page.
    with pytest.raises(HTTPException):
        tenant_from_public_key(new_key(tenant))
    with pytest.raises(HTTPException):
        tenant_from_key(new_public_key(tenant))


@pytest.mark.parametrize(
    "origin,allowed",
    [
        (None, ["https://client.com"]),
        ("", ["https://client.com"]),
        ("https://client.com", []),
        ("https://evil.com", ["https://client.com"]),
        ("https://client.com.evil.com", ["https://client.com"]),
        ("http://client.com", ["https://client.com"]),
    ],
)
def test_origin_allowlist_fails_closed(origin, allowed):
    assert origin_allowed(origin, allowed) is False


def test_origin_allowlist_admits_an_exact_match():
    assert origin_allowed("https://client.com", ["https://a.com", "https://client.com"])


@pytest.mark.parametrize(
    "origin",
    ["https://client.com/path", "client.com", "ftp://client.com", "https://", "javascript:alert(1)"],
)
def test_origin_format_is_scheme_and_host_only(origin):
    with pytest.raises(HTTPException) as error:
        check_origin_format([origin])
    assert error.value.status_code == 422


def test_chatbot_requires_at_least_one_origin():
    # The default must be a deliberate choice, not an empty list that answers nowhere
    # while looking configured.
    with pytest.raises(ValidationError):
        ChatbotInput(knowledge_base_id=uuid4(), name="Support", allowed_origins=[])


def test_visitor_cannot_choose_the_knowledge_base():
    # The public endpoint takes only a question. The knowledge base is read from the
    # chatbot row, so editing the request body cannot reach another one.
    assert set(QuestionInput.model_fields) == {"question"}
    with pytest.raises(ValidationError):
        QuestionInput(question="Hello", knowledge_base_id=str(uuid4()))


def test_malformed_public_key_is_refused_without_touching_the_database():
    client = TestClient(api.app)
    response = client.get(
        "/public/v1/chatbots/not-a-key", headers={"Origin": "https://client.com"}
    )
    assert response.status_code == 401


def test_preflight_is_answered_before_the_static_cors_allowlist():
    # The global CORSMiddleware rejects unknown origins outright, so the widget's
    # preflight must be handled by the middleware wrapping it. If this returns 400
    # the middleware order has regressed and every embedded widget breaks.
    client = TestClient(api.app)
    response = client.options(
        WIDGET + "/chat",
        headers={
            "Origin": "https://client.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "https://client.com"
    assert response.headers["vary"] == "Origin"


def test_preflight_is_not_offered_for_authenticated_routes():
    client = TestClient(api.app)
    response = client.options(
        "/v1/knowledge-bases",
        headers={"Origin": "https://evil.com", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") != "https://evil.com"


def test_rate_limit_allows_then_refuses():
    for _ in range(3):
        rate_limit("visitor", limit=3, window=60)
    with pytest.raises(HTTPException) as error:
        rate_limit("visitor", limit=3, window=60)
    assert error.value.status_code == 429


def test_rate_limit_window_expires_and_buckets_are_released():
    rate_limit("visitor", limit=1, window=-1)
    rate_limit("visitor", limit=1, window=-1)
    assert "visitor" not in api._asked


def test_widget_bundle_is_served_and_cacheable():
    client = TestClient(api.app)
    response = client.get("/widget.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "public, max-age=300"
    assert "attachShadow" in response.text


def test_public_errors_are_readable_by_the_embedding_page():
    # Without this the widget cannot show why it failed: the browser blocks the
    # response body, and a rate limit looks identical to a broken install.
    client = TestClient(api.app)
    response = client.get(
        "/public/v1/chatbots/not-a-key", headers={"Origin": "https://client.com"}
    )
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "https://client.com"
