from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import init_engine_pragmas
from app.jobs.worker import worker
from app.routers import (
    backup,
    captures,
    export,
    health,
    jobs,
    pairing,
    processing,
    search,
    settings as settings_router,
    status,
    sync,
    thoughts,
)

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# 仕様書14「思考本文を通常ログへ出力しない」: uvicornのアクセスログにクエリ文字列や
# ボディが出ないよう、標準のaccessログフォーマットのままにし、独自ログでは
# raw_text/contentを直接loggerへ渡さない運用を徹底する(pipeline.py参照)。
logger = logging.getLogger("brain_twin.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.resolved_database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.resolved_backups_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_exports_dir.mkdir(parents=True, exist_ok=True)

    await init_engine_pragmas()
    worker.start()
    logger.info("Brain Twin server started")
    try:
        yield
    finally:
        await worker.stop()
        logger.info("Brain Twin server stopped")


app = FastAPI(
    title="Brain Twin API",
    version="0.1.0-mvp",
    lifespan=lifespan,
    # Tailscale内部限定運用のため、公開ドキュメントとしてではなく開発補助として/docsを維持する。
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS: 同一オリジン運用が基本だが、PWAをホーム画面追加した際のservice worker経由の
# 挙動を考慮し、明示的に許可されたoriginのみ通す(仕様書14: CORS制限)。
if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail, "detail": None})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # 仕様書9: 表側は静かに。詳細はサーバーログにのみ残し、クライアントへは
    # 不安を煽らない定型文だけを返す(生の原文は例外メッセージに含めない設計を徹底)。
    #
    # 【実バグ修正】以前はこの汎用ハンドラが「保存済みです。整理は少し時間をおいて
    # 行われます。」というcapture(入力保存)専用の文言を、エンドポイントに関わらず
    # 常に返していた。ペアリング等、何も保存されていない操作が失敗した場合にも
    # 同じ文言が返り、「保存された」という誤った安心感を与えてしまう実害があった
    # (実機検証で発見)。汎用ハンドラはどのエンドポイントでも真になる、中立的な
    # 文言のみを返すようにする。
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"message": "今は完了できませんでした。少し時間をおいて、もう一度お試しください。", "detail": "internal_error"},
    )


for r in (health, status, pairing, sync, captures, thoughts, search, processing, jobs, settings_router, export, backup):
    app.include_router(r.router)
