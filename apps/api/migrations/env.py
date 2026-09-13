import os

from alembic import context
from sqlalchemy import create_engine, pool

url = os.environ.get("MIGRATION_DATABASE_URL")
if not url:
    raise RuntimeError(
        "MIGRATION_DATABASE_URL is required; never use the runtime role for migrations"
    )
if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
