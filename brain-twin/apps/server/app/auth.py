"""
仕様書14「認証とセキュリティ」対応。

- ペアリング: PC側で短命コードを発行し、iPhone側でそのコードを入力して
  長期の端末トークンを取得する。
- 端末トークン: サーバーはハッシュ(SHA-256)のみを保持し、平文はペアリング完了時の
  レスポンスでしか返さない。
- レート制限: 個人利用の単一プロセスサーバーという前提で、プロセス内メモリの
  簡易スライディングウィンドウで十分と判断(Redis等の外部依存を増やさない)。
"""
from __future__ import annotations

import hashlib
import secrets
import string
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.trust import is_trusted_local_request
from app.db import get_db
from app.models import SyncDevice

settings = get_settings()

_CODE_ALPHABET = string.ascii_uppercase + string.digits
# 見間違えやすい文字 (0/O, 1/I) を除く。声に出して伝える/手で打つ場面を想定。
_CODE_ALPHABET = "".join(c for c in _CODE_ALPHABET if c not in "0O1I")


def generate_pairing_code(length: int = 8) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def generate_device_token() -> str:
    return secrets.token_hex(settings.device_token_bytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_trusted_local_host(request: Request) -> bool:
    """
    /api/pairing/start はここから初めて信頼を作る操作であり、PC自身
    (docker compose exec経由での直接呼び出し)からのみ許可したい。

    【追加修正】以前はIPアドレスの前方一致(127.0.0.1/172.*/10.*等)だけで判定していたが、
    Web/APIの同一オリジン化(Nginxリバースプロキシ導入)後は、iPhoneからの正規のリクエストも
    Nginxコンテナ経由でserverへ届く際には送信元IPがDocker内部ネットワークのアドレスに
    "見えてしまう" ため、IPだけでは「PCからの直接呼び出し」と「Nginx経由の転送」を
    区別できなくなる。

    そのため一次防御は apps/web/nginx.conf 側で /api/pairing/start を
    edgeで明示的に403ブロックすることに置き、ここでのチェックはその防御が
    何らかの理由で外れた場合の二次防御(多層防御)として機能する。
    実際の判定ロジックは app/core/trust.py (依存フリー、単体テスト済み) に切り出してある。
    """
    return is_trusted_local_request(dict(request.headers), request.client.host if request.client else None)


class RateLimiter:
    """プロセス内メモリのみで完結する簡易スライディングウィンドウ・レートリミッタ。"""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = limit_per_minute
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - 60.0
        hits = self._hits[key]
        while hits and hits[0] < window_start:
            hits.popleft()
        if len(hits) >= self.limit_per_minute:
            return False
        hits.append(now)
        return True


rate_limiter = RateLimiter(settings.rate_limit_per_minute)


async def get_current_device(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SyncDevice:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="端末トークンが必要です")

    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="端末トークンが必要です")

    token_hash = hash_token(token)

    if not rate_limiter.check(token_hash):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="リクエストが多すぎます。少し待ってください")

    result = await db.execute(select(SyncDevice).where(SyncDevice.device_token_hash == token_hash))
    device = result.scalar_one_or_none()

    if device is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効な端末トークンです")
    if device.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="この端末は失効しています")

    return device
