"""Document ingestion tables with tenant-safe relationships."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = ("documents", "document_versions", "chunks", "ingestion_jobs")


def upgrade():
    op.execute("""
        CREATE TABLE documents (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            knowledge_base_id uuid NOT NULL,
            name varchar(255) NOT NULL,
            source_type varchar(32) NOT NULL,
            source_uri text,
            active_version_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, knowledge_base_id)
                REFERENCES knowledge_bases(tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE document_versions (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            document_id uuid NOT NULL,
            version integer NOT NULL CHECK (version > 0),
            status varchar(24) NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','parsing','chunking','embedding','indexed','failed')),
            storage_key text NOT NULL,
            content_type varchar(120) NOT NULL,
            byte_size bigint NOT NULL CHECK (byte_size >= 0),
            checksum_sha256 varchar(64) NOT NULL CHECK (length(checksum_sha256) = 64),
            embedding_provider varchar(64) NOT NULL,
            embedding_model varchar(120) NOT NULL,
            embedding_dimensions integer NOT NULL CHECK (embedding_dimensions > 0),
            error_message text,
            created_at timestamptz NOT NULL DEFAULT now(),
            indexed_at timestamptz,
            UNIQUE (tenant_id, id),
            UNIQUE (document_id, version),
            FOREIGN KEY (tenant_id, document_id)
                REFERENCES documents(tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        ALTER TABLE documents ADD CONSTRAINT documents_active_version_fk
        FOREIGN KEY (tenant_id, active_version_id)
        REFERENCES document_versions(tenant_id, id)
        DEFERRABLE INITIALLY DEFERRED
    """)
    op.execute("""
        CREATE TABLE chunks (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            knowledge_base_id uuid NOT NULL,
            document_id uuid NOT NULL,
            document_version_id uuid NOT NULL,
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            content text NOT NULL CHECK (length(content) > 0),
            token_count integer NOT NULL CHECK (token_count > 0),
            page_number integer CHECK (page_number > 0),
            section text,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            embedding vector,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            UNIQUE (document_version_id, ordinal),
            FOREIGN KEY (tenant_id, knowledge_base_id)
                REFERENCES knowledge_bases(tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, document_id)
                REFERENCES documents(tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, document_version_id)
                REFERENCES document_versions(tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE ingestion_jobs (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            document_version_id uuid NOT NULL,
            stage varchar(24) NOT NULL DEFAULT 'parse'
                CHECK (stage IN ('parse','chunk','embed','finalize')),
            status varchar(24) NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','completed','failed','cancelled')),
            attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
            idempotency_key varchar(160) NOT NULL,
            error_message text,
            started_at timestamptz,
            completed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, idempotency_key),
            FOREIGN KEY (tenant_id, document_version_id)
                REFERENCES document_versions(tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX documents_kb_idx ON documents(tenant_id, knowledge_base_id)")
    op.execute("CREATE INDEX versions_document_idx ON document_versions(tenant_id, document_id)")
    op.execute("CREATE INDEX chunks_kb_idx ON chunks(tenant_id, knowledge_base_id)")
    op.execute("CREATE INDEX chunks_version_idx ON chunks(tenant_id, document_version_id, ordinal)")
    op.execute("CREATE INDEX jobs_status_idx ON ingestion_jobs(tenant_id, status, created_at)")
    op.execute("CREATE INDEX chunks_metadata_idx ON chunks USING gin(metadata)")

    for table in TABLES:
        rule = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({rule}) WITH CHECK ({rule})")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON documents TO rag_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON document_versions TO rag_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON chunks TO rag_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion_jobs TO rag_app")


def downgrade():
    op.execute("ALTER TABLE documents DROP CONSTRAINT documents_active_version_fk")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
