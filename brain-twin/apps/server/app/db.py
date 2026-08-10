"""非同期SQLAlchemyエンジン/セッション。

SQLiteは既定では外部キー制約が無効なため、接続のたびに `PRAGMA foreign_keys = ON`
を発行する(db_schema.sqlのCASCADE削除が機能する前提)。個人利用の単一プロセス
運用のため、コネクションプールは単純なStaticPool的運用でよいが、
aiosqliteの標準プールで十分(同時書き込みはWALで緩和する)。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings

settings = get_settings()

# StaticPool + connect_args={"check_same_thread": False}: 単一プロセスのasyncioイベント
# ループから使う分には安全で、SQLiteファイルへの同時アクセスはWALモードとSQLite自体の
# ロックに委ねる(個人利用規模でRedis等の外部ロックは過剰と判断)。
engine = create_async_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.close()


async def init_engine_pragmas() -> None:
    """起動時に一度、接続を張ってPRAGMAが効いていることを確定させる
    (lazy接続だと最初のリクエストまでエラーに気づけないため)。"""
    async with engine.connect() as conn:
        await conn.execute(text("PRAGMA foreign_keys"))


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPIの`Depends(get_db)`用。例外時はrollbackしてから伝播させる。"""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """ワーカー等、FastAPIのリクエストスコープ外で使うためのコンテキストマネージャ版。"""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
