"""Dashboard users and their login sessions.

Both tables follow the same tenant row-level security as everything else. The one thing that has to
cross tenants is finding who is logging in, since an email arrives before the tenant is known.
`find_login` does exactly that and nothing more: one exact, case-insensitive email in, one row of
(user, tenant, password hash) out, callable only by the runtime role.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE users (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            email varchar(254) NOT NULL,
            password_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            disabled_at timestamptz,
            UNIQUE (tenant_id, id)
        )
    """)
    # Global, not per tenant: login is by email alone.
    op.execute("CREATE UNIQUE INDEX users_email_key ON users (lower(email))")
    op.execute("""
        CREATE TABLE user_sessions (
            token_hash char(64) PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX user_sessions_expiry_idx ON user_sessions(expires_at)")
    rule = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    for table in ("users", "user_sessions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({rule}) WITH CHECK ({rule})")
    # The API reads users to check they are still enabled and never writes them: accounts are
    # made and changed by the administrator CLI, which connects as the migration role.
    op.execute("GRANT SELECT ON users TO rag_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON user_sessions TO rag_app")
    # Runs as the role that owns it (the migration role), which is not subject to row security.
    op.execute("""
        CREATE FUNCTION find_login(address text)
        RETURNS TABLE (user_id uuid, tenant_id uuid, password_hash text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
            SELECT id, tenant_id, password_hash FROM users
            WHERE lower(email) = lower(address) AND disabled_at IS NULL
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION find_login(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION find_login(text) TO rag_app")


def downgrade():
    op.execute("DROP FUNCTION find_login(text)")
    op.execute("DROP TABLE user_sessions")
    op.execute("DROP TABLE users")
