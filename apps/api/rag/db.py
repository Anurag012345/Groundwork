from functools import lru_cache
from uuid import UUID

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.pool import NullPool

from rag.config import settings


@lru_cache
def engine():
    if not settings().database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_engine(
        settings().database_url, poolclass=NullPool, connect_args={"connect_timeout": 5}
    )


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"


def set_tenant(connection, tenant_id: UUID):
    # Transaction-scoped: safe with PgBouncer and concurrent function invocations.
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"),
        {"tenant": str(tenant_id)},
    )


TENANT_TABLES = (
    "tenants",
    "api_keys",
    "knowledge_bases",
    "documents",
    "document_versions",
    "chunks",
    "ingestion_jobs",
    "chatbots",
)


def assert_runtime_role(connection: Connection):
    names = ", ".join(f"'{table}'" for table in TENANT_TABLES)
    safe = connection.execute(
        text(f"""
        SELECT NOT (r.rolsuper OR r.rolbypassrls)
          AND count(c.oid) = {len(TENANT_TABLES)}
          AND bool_and(c.relrowsecurity AND c.relforcerowsecurity
                       AND c.relowner <> r.oid)
        FROM pg_roles r
        LEFT JOIN pg_class c ON c.relnamespace = 'public'::regnamespace
          AND c.relname IN ({names})
        WHERE r.rolname = current_user
        GROUP BY r.rolsuper, r.rolbypassrls
    """)
    ).scalar()
    if not safe:
        raise RuntimeError("Runtime database role or RLS configuration is unsafe")
