"""Pin one embedding space to each knowledge base."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE knowledge_bases
        ADD COLUMN embedding_provider varchar(64) NOT NULL DEFAULT 'ollama',
        ADD COLUMN embedding_model varchar(120) NOT NULL DEFAULT 'nomic-embed-text',
        ADD COLUMN embedding_dimensions integer NOT NULL DEFAULT 768
            CHECK (embedding_dimensions > 0)
    """)


def downgrade():
    op.execute("""
        ALTER TABLE knowledge_bases
        DROP COLUMN embedding_dimensions,
        DROP COLUMN embedding_model,
        DROP COLUMN embedding_provider
    """)
