"""Explicit local/admin CLI. Never exposed as a public HTTP endpoint."""

import argparse
import os
from uuid import uuid4

from sqlalchemy import create_engine, text

from rag.db import set_tenant
from rag.security import hash_key, new_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    if not 1 <= len(args.name.strip()) <= 120:
        parser.error("Tenant name must have 1–120 characters")
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if not database_url:
        parser.error("MIGRATION_DATABASE_URL is required")
    tenant_id = uuid4()
    key = new_key(tenant_id)
    with create_engine(database_url).begin() as conn:
        set_tenant(conn, tenant_id)
        conn.execute(
            text("INSERT INTO tenants(id, name) VALUES (:id, :name)"),
            {"id": tenant_id, "name": args.name.strip()},
        )
        conn.execute(
            text("INSERT INTO api_keys(id, tenant_id, key_hash) VALUES (:id, :tenant, :hash)"),
            {"id": uuid4(), "tenant": tenant_id, "hash": hash_key(key)},
        )
    print(f"Tenant: {tenant_id}\nAPI key (shown once): {key}")


if __name__ == "__main__":
    main()
