"""Tenant foundation and fail-closed RLS."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = ("tenants", "api_keys", "knowledge_bases")


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE tenants (
            id uuid PRIMARY KEY,
            name varchar(120) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE api_keys (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            key_hash varchar(64) NOT NULL UNIQUE,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE knowledge_bases (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name varchar(120) NOT NULL,
            description text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id)
        )
    """)
    op.execute("CREATE INDEX api_keys_tenant_idx ON api_keys(tenant_id)")
    op.execute("CREATE INDEX knowledge_bases_tenant_idx ON knowledge_bases(tenant_id)")
    for table in TABLES:
        column = "id" if table == "tenants" else "tenant_id"
        rule = f"{column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({rule}) WITH CHECK ({rule})")
    # Role is provisioned separately; migrations do not create credentials.
    op.execute("GRANT USAGE ON SCHEMA public TO rag_app")
    op.execute("GRANT SELECT ON tenants, api_keys TO rag_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON knowledge_bases TO rag_app")


def downgrade():
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
    # pgvector is intentionally preserved; other applications may use the extension.
