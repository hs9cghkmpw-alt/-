"""依存フリー(標準ライブラリのsqlite3のみ)。手動/定期バックアップの実体。
仕様書15。sqlite3標準の Online Backup API を使うため、アプリがWALモードで
書き込み中でも安全にホットバックアップできる。app/routers/backup.py (API経由)と
scripts/backup_cli.py (cron/タスクスケジューラ経由)の両方から呼ばれる共通ロジック。"""
from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_FILENAME_PREFIX = "brain_twin_"
_FILENAME_SUFFIX = ".sqlite3"


@dataclass
class BackupResult:
    ok: bool
    path: Path | None = None
    message: str = ""
    deleted_old: list[str] = field(default_factory=list)


def _generate_filename(now: datetime) -> str:
    return f"{_FILENAME_PREFIX}{now.strftime('%Y%m%d_%H%M%S_%f')}_{secrets.token_hex(3)}{_FILENAME_SUFFIX}"


def list_backups(backup_dir: Path) -> list[Path]:
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob(f"{_FILENAME_PREFIX}*{_FILENAME_SUFFIX}"), key=lambda p: p.name)


def _rotate(backup_dir: Path, keep: int) -> list[str]:
    files = list_backups(backup_dir)
    deleted: list[str] = []
    while len(files) > keep:
        oldest = files.pop(0)
        try:
            oldest.unlink()
            deleted.append(oldest.name)
        except FileNotFoundError:
            pass
    return deleted


def backup_and_rotate(db_path: Path, backup_dir: Path, keep: int = 7) -> BackupResult:
    db_path = Path(db_path)
    backup_dir = Path(backup_dir)

    if not db_path.exists():
        return BackupResult(ok=False, message=f"データベースファイルが見つかりません: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / _generate_filename(datetime.now(timezone.utc))

    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(str(db_path))
        target = sqlite3.connect(str(dest))
        source.backup(target)
    except sqlite3.Error as e:
        if dest.exists():
            dest.unlink(missing_ok=True)
        return BackupResult(ok=False, message=f"バックアップに失敗しました: {e}")
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()

    deleted = _rotate(backup_dir, keep)
    return BackupResult(ok=True, path=dest, message="バックアップが完了しました", deleted_old=deleted)


def restore_from(backup_file: Path, db_path: Path, *, safety_copy_dir: Path | None = None) -> BackupResult:
    """復元の前に、現在のDBを安全コピーしてから上書きする(仕様書15)。"""
    backup_file = Path(backup_file)
    db_path = Path(db_path)

    if not backup_file.exists():
        return BackupResult(ok=False, message=f"バックアップファイルが見つかりません: {backup_file}")

    if db_path.exists() and safety_copy_dir is not None:
        safety_copy_dir.mkdir(parents=True, exist_ok=True)
        safety_dest = safety_copy_dir / f"pre_restore_{_generate_filename(datetime.now(timezone.utc))}"
        source = sqlite3.connect(str(db_path))
        target = sqlite3.connect(str(safety_dest))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    backup_conn = sqlite3.connect(str(backup_file))
    restored_conn = sqlite3.connect(str(db_path))
    try:
        backup_conn.backup(restored_conn)
    except sqlite3.Error as e:
        return BackupResult(ok=False, message=f"復元に失敗しました: {e}")
    finally:
        restored_conn.close()
        backup_conn.close()

    return BackupResult(ok=True, path=db_path, message="復元が完了しました")
