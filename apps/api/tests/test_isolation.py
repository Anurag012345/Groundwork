"""Run against a disposable migrated PostgreSQL database, never production."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from rag.db import set_tenant

pytestmark = pytest.mark.integration


def test_rls_boundaries():
    admin_url = os.environ.get("TEST_ADMIN_DATABASE_URL")
    runtime_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url or not runtime_url:
        pytest.skip(
            "Set TEST_ADMIN_DATABASE_URL and TEST_DATABASE_URL for PostgreSQL isolation tests"
        )
    admin, runtime = create_engine(admin_url), create_engine(runtime_url)
    a, b, kb = uuid4(), uuid4(), uuid4()
    try:
        with admin.begin() as conn:
            for tenant in (a, b):
                set_tenant(conn, tenant)
                conn.execute(
                    text("INSERT INTO tenants(id,name) VALUES (:id,'isolation test')"),
                    {"id": tenant},
                )
        with runtime.begin() as conn:
            set_tenant(conn, a)
            conn.execute(
                text("INSERT INTO knowledge_bases(id,tenant_id,name) VALUES (:id,:t,'A')"),
                {"id": kb, "t": a},
            )
        with runtime.begin() as conn:
            set_tenant(conn, b)
            assert (
                conn.execute(
                    text("SELECT id FROM knowledge_bases WHERE id=:id"), {"id": kb}
                ).first()
                is None
            )
            assert (
                conn.execute(text("DELETE FROM knowledge_bases WHERE id=:id"), {"id": kb}).rowcount
                == 0
            )
        with pytest.raises(DBAPIError), runtime.begin() as conn:
            set_tenant(conn, b)
            conn.execute(
                text("INSERT INTO knowledge_bases(id,tenant_id,name) VALUES (:id,:t,'bad')"),
                {"id": uuid4(), "t": a},
            )
        with runtime.begin() as conn:
            assert conn.execute(text("SELECT id FROM knowledge_bases")).first() is None
    finally:
        with admin.begin() as conn:
            for tenant in (a, b):
                set_tenant(conn, tenant)
                conn.execute(text("DELETE FROM tenants WHERE id=:id"), {"id": tenant})
        admin.dispose()
        runtime.dispose()
