from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_device_token, generate_pairing_code, hash_token, is_trusted_local_host, rate_limiter
from app.config import get_settings
from app.db import get_db
from app.models import PairingCode, SyncDevice
from app.schemas import PairingCompleteRequest, PairingCompleteResponse, PairingStartResponse
from app.utils.uuids import new_id

router = APIRouter(tags=["pairing"])
settings = get_settings()


@router.post("/api/pairing/start", response_model=PairingStartResponse)
async def pairing_start(request: Request, db: AsyncSession = Depends(get_db)) -> PairingStartResponse:
    """
    PC側でのみ呼び出せる(仕様書14: 初回セットアップ時にPCでペアリングコード発行)。
    iPhoneからTailscale経由で直接この時点のエンドポイントを叩けないよう、
    呼び出し元ホストを制限する。README/SETUP_IPHONE.mdでは
    `docker compose exec server curl -X POST http://localhost:8000/api/pairing/start`
    のようにPC上から実行する手順を案内する。
    """
    if not is_trusted_local_host(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このエンドポイントはPC上(localhost)からのみ呼び出せます。iPhoneからは呼び出せません。",
        )

    now = datetime.now(timezone.utc)
    code = generate_pairing_code()
    expires_at = now + timedelta(seconds=settings.pairing_code_ttl_seconds)
    db.add(PairingCode(code=code, created_at=now, expires_at=expires_at, consumed_at=None))
    await db.commit()

    return PairingStartResponse(
        code=code,
        expires_at=expires_at.isoformat().replace("+00:00", "Z"),
        expires_in_seconds=settings.pairing_code_ttl_seconds,
    )


@router.post("/api/pairing/complete", response_model=PairingCompleteResponse)
async def pairing_complete(body: PairingCompleteRequest, request: Request, db: AsyncSession = Depends(get_db)) -> PairingCompleteResponse:
    """iPhone側でコードを入力し、長期端末トークンを発行する。"""
    client_host = request.client.host if request.client else "unknown"
    if not rate_limiter.check(f"pairing:{client_host}"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="試行回数が多すぎます。少し待ってください")

    now = datetime.now(timezone.utc)
    result = await db.execute(select(PairingCode).where(PairingCode.code == body.code.strip().upper()))
    pairing = result.scalar_one_or_none()

    if pairing is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="コードが正しくありません")
    if pairing.consumed_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="このコードは既に使用されています")
    expires_at = pairing.expires_at if pairing.expires_at.tzinfo else pairing.expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="コードの有効期限が切れています。PCで再発行してください")

    pairing.consumed_at = now

    token = generate_device_token()
    device = SyncDevice(
        id=new_id(),
        device_name=body.device_name,
        device_token_hash=hash_token(token),
        last_seen_at=now,
        revoked_at=None,
        created_at=now,
    )
    db.add(device)
    await db.commit()

    return PairingCompleteResponse(device_id=device.id, device_token=token)
