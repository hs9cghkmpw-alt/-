#!/usr/bin/env bash
# Brain Twin バックアップの自動登録解除 (Linux / macOS, cron)
#
# 実行方法:
#   ./scripts/uninstall_backup_cron.sh
set -euo pipefail

MARKER="# brain-twin-daily-backup (managed by scripts/install_backup_cron.sh)"

if ! command -v crontab >/dev/null 2>&1; then
  echo "[エラー] crontabコマンドが見つかりません。" >&2
  exit 1
fi

EXISTING="$(crontab -l 2>/dev/null || true)"

if ! echo "$EXISTING" | grep -q -F "$MARKER"; then
  echo "[INFO] Brain Twin用のcron登録は見つかりませんでした。何も行いません。"
  exit 0
fi

FILTERED="$(echo "$EXISTING" | grep -v -F "$MARKER" || true)"
echo "$FILTERED" | crontab -

echo "[OK] cronからBrain Twinのバックアップ登録を解除しました。"
echo "(過去のバックアップファイルやログは削除されません。data/backups/ に残っています。)"
