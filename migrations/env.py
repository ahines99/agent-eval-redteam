"""Migration environment; DATABASE_URL overrides the local SQLite default."""
from __future__ import annotations

import os
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from agent_eval_redteam.adapters.repositories import metadata

config = context.config
url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))

if context.is_offline_mode():
    context.configure(url=url, target_metadata=metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    with create_engine(url, poolclass=NullPool).connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
