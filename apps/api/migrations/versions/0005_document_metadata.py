"""Document metadata: free-form key/values that retrieval can filter on."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE documents ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}'")
    # Serves the `metadata @> filter` containment test retrieval uses.
    op.execute(
        "CREATE INDEX documents_metadata_idx ON documents USING gin (metadata jsonb_path_ops)"
    )


def downgrade():
    op.execute("DROP INDEX documents_metadata_idx")
    op.execute("ALTER TABLE documents DROP COLUMN metadata")
