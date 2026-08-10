#!/usr/bin/env bash
# Brain Twin バックアップの自動登録 (Linux / macOS, cron)
#
# 実行方法:
#   ./scripts/install_backup_cron.sh          # 毎日3:00に登録
#   ./scripts/install_backup_cron.sh 4 30     # 毎日4:30に登録(時 分)
#
# 解除方法:
#   ./scripts/uninstall_backup_cron.sh
#
# crontab を手で編集する必要はありません。目印コメント(MARKER)を使って
# 既存のBrain Twin用エントリだけを安全に検出・置き換えます(重複登録を防ぐ)。
#
# 【追加修正5】
#  - リポジトリのパスに空白(例: "My Projects", "Brain Twin")が含まれても
#    正しく動くよう、cron行内のパスを `printf '%q'` でシェル安全にエスケープする。
#    cronは通常 `sh -c "<コマンド文字列>"` としてコマンドを実行するため、
#    ここで施したエスケープはその`sh -c`解釈時に正しく1つのパスとして復元される
#    (このリポジトリの開発環境で実際に検証済み。VERIFICATION.md参照)。
#  - Hour(0-23)/Minute(0-59)を検証し、不正な値なら**crontabを一切書き換えずに**終了する。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOUR="${1:-3}"
MINUTE="${2:-0}"
MARKER="# brain-twin-daily-backup (managed by scripts/install_backup_cron.sh)"

# --- 入力検証: 数値以外・範囲外は、crontabに一切触れずに終了する ---
is_valid_integer() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;  # 数値以外(空文字・符号・小数点なども拒否)
    *) return 0 ;;
  esac
}

if ! is_valid_integer "$HOUR" || [ "$HOUR" -lt 0 ] || [ "$HOUR" -gt 23 ]; then
  echo "[エラー] Hourは0〜23の整数で指定してください(指定値: '$HOUR')。crontabは変更していません。" >&2
  exit 2
fi
if ! is_valid_integer "$MINUTE" || [ "$MINUTE" -lt 0 ] || [ "$MINUTE" -gt 59 ]; then
  echo "[エラー] Minuteは0〜59の整数で指定してください(指定値: '$MINUTE')。crontabは変更していません。" >&2
  exit 2
fi

if ! command -v crontab >/dev/null 2>&1; then
  echo "[エラー] crontabコマンドが見つかりません。macOS/Linuxで実行しているか確認してください。" >&2
  echo "Windowsをお使いの場合は scripts\\install_backup_task.ps1 を使ってください。" >&2
  exit 1
fi

chmod +x "$REPO_ROOT/scripts/backup.sh"

# --- パスを安全にエスケープする(空白・特殊文字を含んでいてもよい) ---
BACKUP_SCRIPT_Q="$(printf '%q' "$REPO_ROOT/scripts/backup.sh")"
LOG_FILE_Q="$(printf '%q' "$REPO_ROOT/data/backups/backup.log")"
CRON_LINE="${MINUTE} ${HOUR} * * * ${BACKUP_SCRIPT_Q} >> ${LOG_FILE_Q} 2>&1 ${MARKER}"

# 既存のcrontabからBrain Twin用の行(MARKER付き)だけを取り除いた上で、新しい行を追加する。
# こうすることで、時刻を変えて再実行しても重複登録にならない。
EXISTING="$(crontab -l 2>/dev/null || true)"
FILTERED="$(echo "$EXISTING" | grep -v -F "$MARKER" || true)"

{
  if [ -n "$FILTERED" ]; then
    echo "$FILTERED"
  fi
  echo "$CRON_LINE"
} | crontab -

echo "[OK] cronに登録しました: 毎日 $(printf '%02d' "$HOUR"):$(printf '%02d' "$MINUTE") にバックアップを実行します。"
echo "登録内容:   $CRON_LINE"
echo "確認:   crontab -l"
echo "ログ:   $REPO_ROOT/data/backups/backup.log"
echo "解除:   ./scripts/uninstall_backup_cron.sh"
echo ""
echo "注意(macOS): cron経由でDockerコマンドを実行するには、ターミナルアプリに"
echo "『フルディスクアクセス』の権限が必要な場合があります"
echo "(システム設定 → プライバシーとセキュリティ → フルディスクアクセス)。"
