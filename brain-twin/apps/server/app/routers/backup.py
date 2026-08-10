from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_device
from app.config import get_settings
from app.core.backup_engine import backup_and_rotate
from app.models import SyncDevice
from app.schemas import BackupResponse

router = APIRouter(tags=["backup"])
settings = get_settings()


@router.post("/api/backup", response_model=BackupResponse)
async def trigger_backup(_device: SyncDevice = Depends(get_current_device)) -> BackupResponse:
    """
    仕様書15『手動バックアップ』。自動バックアップは scripts/backup.sh (cron/タスクスケジューラ)
    から同じ app.core.backup_engine を叩く想定で、このAPIはアプリ内『今すぐバックアップ』ボタン用。
    """
    result = backup_and_rotate(
        settings.resolved_database_path,
        settings.resolved_backups_dir,
        keep=settings.backup_retention_generations,
    )
    return BackupResponse(
        ok=result.ok,
        path=str(result.path) if result.path else None,
        message=result.message,
        deleted_old=result.deleted_old,
    )
