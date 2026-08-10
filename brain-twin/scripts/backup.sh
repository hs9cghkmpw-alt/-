#!/usr/bin/env bash
# Brain Twin 手動/定期バックアップ (macOS / Linux)
#
# 手動実行:
#   ./scripts/backup.sh
#
# 定期実行の自動登録は scripts/install_backup_cron.sh を使ってください
# (cronの書式を手で編集する必要はありません)。
#
# ログは data/backups/backup.log に追記されます(スケジューラ経由でも
# 手動実行でも同じファイルに記録され、実行時刻・成功/失敗が追跡できます)。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LOG_DIR="$REPO_ROOT/data/backups"
LOG_FILE="$LOG_DIR/backup.log"
mkdir -p "$LOG_DIR"

echo "[$(date -Iseconds)] バックアップを開始します" | tee -a "$LOG_FILE"

# パイプの左側(docker compose exec)の終了コードをPIPESTATUSで正しく取得する。
# { } でグループ化して変数に閉じ込めると、パイプの左側はサブシェルで実行されるため
# 変数がパイプの外(呼び出し元シェル)へ伝播しない問題があるため、この形にしている。
docker compose exec -T server python scripts/backup_cli.py 2>&1 | tee -a "$LOG_FILE"
BACKUP_EXIT_CODE=${PIPESTATUS[0]}

if [ "$BACKUP_EXIT_CODE" -eq 0 ]; then
  echo "[$(date -Iseconds)] バックアップ処理が正常終了しました" | tee -a "$LOG_FILE"
else
  echo "[$(date -Iseconds)] [失敗] バックアップ処理がエラー終了しました(終了コード: $BACKUP_EXIT_CODE)" | tee -a "$LOG_FILE"
fi

exit "$BACKUP_EXIT_CODE"
