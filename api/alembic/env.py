from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  registers tables on Base.metadata
from app.db import DATABASE_URL, Base, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with make_engine().connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # Batch mode rebuilds a table (copy, drop, rename). With foreign keys on, dropping a table that
            # others point at (e.g. users, from sessions and deals) fails, so turn them off for the migration
            # and check every reference is still valid before committing. The pragma only works outside a
            # transaction, hence the commit first.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        # Batch mode lets SQLite handle ALTER TABLE-style changes in later migrations.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
            if sqlite:
                broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(f"Migration left broken foreign keys: {broken[:10]}")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
