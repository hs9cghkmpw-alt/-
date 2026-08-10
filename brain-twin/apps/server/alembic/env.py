from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.models import Base

# alembic.iniのロギング設定を適用する。
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 実際のDB接続先は環境変数(.env / docker-compose)由来のapp.config設定を正とする。
# alembic.iniのsqlalchemy.urlはプレースホルダのため、ここで実行時に上書きする。
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

# 将来 `alembic revision --autogenerate` を使う場合のために対象メタデータを設定する。
# 実際のテーブル生成自体は app/db_schema.sql (FTS5仮想テーブル・トリガーを含む) を
# versions/0001_initial.py が直接実行する方式を取っている。
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
