#!/usr/bin/env python3
"""バックアップからの復元CLI (scripts/restore.sh, scripts/restore.ps1 から呼ばれる)。
破壊的操作のため既定では対話的確認を挟む(--yesでスキップ。統合テスト等の
非対話環境用)。復元前に現在のDBは自動的に安全コピーされる(仕様書15)。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.core.backup_engine import list_backups, restore_from  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Brain Twin バックアップ復元")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="バックアップ一覧を表示する")
    group.add_argument("--latest", action="store_true", help="最新のバックアップから復元する")
    group.add_argument("--file", metavar="FILENAME", help="指定したバックアップファイルから復元する")
    parser.add_argument("--yes", action="store_true", help="確認プロンプトをスキップする")
    args = parser.parse_args()

    settings = get_settings()
    backups = list_backups(settings.resolved_backups_dir)

    if args.list or not (args.latest or args.file):
        if not backups:
            print("バックアップがありません。")
            return 0
        for b in backups:
            print(b.name)
        return 0

    target = backups[-1] if args.latest else settings.resolved_backups_dir / args.file
    if not target.exists():
        print(f"[NG] バックアップファイルが見つかりません: {target}", file=sys.stderr)
        return 1

    if not args.yes:
        answer = input(f"{target.name} から復元します。現在のDBは上書きされます。よろしいですか? [y/N]: ")
        if answer.strip().lower() != "y":
            print("中止しました。")
            return 1

    result = restore_from(target, settings.resolved_database_path, safety_copy_dir=settings.resolved_backups_dir)
    if result.ok:
        print(f"[OK] {result.message}")
        return 0
    print(f"[NG] {result.message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
