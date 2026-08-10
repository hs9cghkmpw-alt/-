"""アプリ内『設定』画面用API。.env由来の値はプロセス再起動なしに変えられないため、
実行時に変更できるのは app_settings テーブルへ保存する一部の項目
(Ollamaのモデル名等)に限定する(仕様書16)。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_device
from app.config import get_settings
from app.db import get_db
from app.models import AppSetting, SyncDevice
from app.schemas import SettingsOut, SettingUpdate

router = APIRouter(tags=["settings"])
settings = get_settings()

# 実行時に上書き可能な項目のみを許可する(任意のkeyを書き込める汎用APIにはしない)。
_MUTABLE_KEYS = {"ollama_model", "ollama_embedding_model"}


def _override_value(overrides: dict, key: str, default: str) -> str:
    override = overrides.get(key)
    if isinstance(override, dict) and "value" in override:
        return override["value"]
    return default


@router.get("/api/settings", response_model=SettingsOut)
async def get_app_settings(
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> SettingsOut:
    result = await db.execute(select(AppSetting).where(AppSetting.key.in_(_MUTABLE_KEYS)))
    overrides = {row.key: row.value_json for row in result.scalars().all()}

    return SettingsOut(
        ollama_base_url=settings.ollama_base_url,
        ollama_model=_override_value(overrides, "ollama_model", settings.ollama_model),
        ollama_embedding_model=_override_value(overrides, "ollama_embedding_model", settings.ollama_embedding_model),
        backup_retention_generations=settings.backup_retention_generations,
        overrides=overrides,
    )


@router.put("/api/settings", response_model=SettingsOut)
async def update_app_setting(
    body: SettingUpdate,
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> SettingsOut:
    if body.key not in _MUTABLE_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{body.key}' は実行時に変更できません(対応項目: {sorted(_MUTABLE_KEYS)})",
        )

    now = datetime.now(timezone.utc)
    existing = await db.execute(select(AppSetting).where(AppSetting.key == body.key))
    row = existing.scalar_one_or_none()
    value_json = {"value": body.value}
    if row is None:
        db.add(AppSetting(key=body.key, value_json=value_json, updated_at=now))
    else:
        row.value_json = value_json
        row.updated_at = now
    await db.commit()

    return await get_app_settings(db=db, _device=_device)
