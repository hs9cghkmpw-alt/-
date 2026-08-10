"""全データのJSONエクスポート(仕様書18)。外部AI API等へは一切送信しない
(README『13. 外部へ送信されるデータの有無』)。ファイルは data/exports/ へ
書き出すのみで、レスポンスとしても本文はそのまま返す。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_device
from app.config import get_settings
from app.db import get_db
from app.models import Capture, SyncDevice, Thought
from app.schemas import ExportResponse
from app.serializers import capture_to_out, load_thought_entities_batch, thought_to_out

router = APIRouter(tags=["export"])
settings = get_settings()


@router.post("/api/export", response_model=ExportResponse)
async def export_data(
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> ExportResponse:
    captures_result = await db.execute(select(Capture).where(Capture.deleted_at.is_(None)))
    captures = list(captures_result.scalars().all())

    thoughts_result = await db.execute(select(Thought).where(Thought.deleted_at.is_(None)))
    thoughts = list(thoughts_result.scalars().all())
    entities_by_thought = await load_thought_entities_batch(db, [t.id for t in thoughts])

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "captures": [capture_to_out(c).model_dump() for c in captures],
        "thoughts": [thought_to_out(t, entities_by_thought.get(t.id, [])).model_dump() for t in thoughts],
    }

    exports_dir = settings.resolved_exports_dir
    exports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"brain_twin_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    dest = exports_dir / filename
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return ExportResponse(
        ok=True,
        path=str(dest),
        message="エクスポートが完了しました",
        thought_count=len(thoughts),
        capture_count=len(captures),
    )
