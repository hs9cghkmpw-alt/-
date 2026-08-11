"""add thoughts.done_at (TODO機能)

「やること」として使える思考にチェックを付けられるようにするための追加専用カラム。
既存データ・既存カラムには一切触れない(NULL許容の新規カラムをADDするのみ)。
db_schema.sql (新規インストール時に0001が一括適用する版) にも同じ定義を追加済みで、
新規/既存どちらの経路でも最終的なスキーマは一致する。

Revision ID: 0002_add_thought_done_at
Revises: 0001_initial
Create Date: 2026-08-11

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_add_thought_done_at"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _raw_dbapi_connection():
    bind = op.get_bind()
    proxied = bind.connection
    for attr in ("dbapi_connection", "driver_connection"):
        raw = getattr(proxied, attr, None)
        if raw is not None:
            return raw
    return proxied


def upgrade() -> None:
    conn = _raw_dbapi_connection()
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(thoughts)").fetchall()}
    if "done_at" not in existing_columns:
        conn.execute("ALTER TABLE thoughts ADD COLUMN done_at TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thoughts_done_at ON thoughts (done_at)")
    conn.commit()


def downgrade() -> None:
    # SQLiteはDROP COLUMNの制約が多く、個人利用のローカルDBでダウングレードのために
    # データ再構築リスクを負う価値は無いと判断し、他のマイグレーション同様に非対応とする。
    raise NotImplementedError("このマイグレーションはdowngradeに対応していません。")
