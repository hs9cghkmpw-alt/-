"""仕様書の同一オリジン化(Nginx)後、`/api/health` は認証なしで疎通確認に使われる
(setup.sh・scripts/verify_integration.sh参照)。SPAのindex.htmlへフォールバックされて
いないことを見分けるため、必ずJSONのみを返す。"""
from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", app_name=settings.app_name, version="0.1.0-mvp")
