"""Public chatbots: the widget's identity, knowledge base, and origin allowlist."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    # The composite foreign key makes pointing a chatbot at another tenant's
    # knowledge base impossible in the database, not only in the application.
    op.execute("""
        CREATE TABLE chatbots (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            knowledge_base_id uuid NOT NULL,
            public_key varchar(120) NOT NULL UNIQUE,
            name varchar(120) NOT NULL,
            greeting text NOT NULL DEFAULT '',
            allowed_origins text[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, knowledge_base_id)
                REFERENCES knowledge_bases(tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX chatbots_tenant_idx ON chatbots(tenant_id)")
    rule = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute("ALTER TABLE chatbots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chatbots FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON chatbots USING ({rule}) WITH CHECK ({rule})")
    op.execute("GRANT SELECT, INSERT, DELETE ON chatbots TO rag_app")


def downgrade():
    op.execute("DROP TABLE chatbots")
