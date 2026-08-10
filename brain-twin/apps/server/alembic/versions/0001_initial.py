"""initial schema

apps/server/app/db_schema.sql をそのまま実行する。テーブル定義に加えて
FTS5(trigramトークナイザ)の仮想テーブルとそれを同期するトリガーを含むため、
SQLAlchemyのop.create_table()等では表現しきれず、生SQLの実行で統一している。
このSQLの意味論は verification/db_schema_check.py で個別に検証済み。

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-10

"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA_SQL_PATH = Path(__file__).resolve().parents[2] / "app" / "db_schema.sql"


def _raw_dbapi_connection():
    bind = op.get_bind()
    proxied = bind.connection
    for attr in ("dbapi_connection", "driver_connection"):
        raw = getattr(proxied, attr, None)
        if raw is not None:
            return raw
    return proxied


def upgrade() -> None:
    sql = _SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    _raw_dbapi_connection().executescript(sql)


def downgrade() -> None:
    # 個人利用のローカルDBであり、ダウングレードでのデータ保全は想定していない
    # (ロールバックしたい場合は scripts/restore.sh でバックアップから復元する)。
    raise NotImplementedError("このマイグレーションはdowngradeに対応していません。データが必要ならscripts/restore.shで復元してください。")
