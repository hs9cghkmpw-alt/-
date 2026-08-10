#!/usr/bin/env python3
"""cron/タスクスケジューラ (scripts/backup.sh, scripts/backup.ps1) から呼ばれる
バックアップCLI。app.core.backup_engine を使い、API経由のバックアップ
(app/routers/backup.py の `POST /api/backup`)と完全に同じロジックで動作する。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.core.backup_engine import backup_and_rotate  # noqa: E402


def main() -> int:
    settings = get_settings()
    result = backup_and_rotate(
        settings.resolved_database_path,
        settings.resolved_backups_dir,
        keep=settings.backup_retention_generations,
    )
    if result.ok:
        print(f"[OK] {result.message}: {result.path}")
        if result.deleted_old:
            print(f"[INFO] 古い世代を削除しました: {', '.join(result.deleted_old)}")
        return 0
    print(f"[NG] {result.message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
