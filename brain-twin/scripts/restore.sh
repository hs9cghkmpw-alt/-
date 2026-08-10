#!/usr/bin/env bash
# Brain Twin バックアップからの復元 (macOS / Linux)
#
# 一覧表示:
#   ./scripts/restore.sh --list
# 最新から復元:
#   ./scripts/restore.sh --latest
# 特定のファイルから復元:
#   ./scripts/restore.sh --file brain_twin_20260730_030000_000000_abc123.sqlite3
#
# 復元は破壊的な操作です。実行前に現在のDBは自動的に安全コピーされますが、
# 復元自体は元に戻せません(意図した通り正しいバックアップか確認してください)。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ "$#" -eq 0 ]; then
  echo "使い方: $0 [--list | --latest | --file <ファイル名>]"
  docker compose exec -T server python scripts/restore_cli.py --list
  exit 0
fi

# --list はTTYが無くても実行できるが、実際の復元(--file/--latest)は
# 対話的確認のため -T を付けずttyを割り当てる。
if [[ "$1" == "--list" ]]; then
  docker compose exec -T server python scripts/restore_cli.py --list
else
  docker compose exec server python scripts/restore_cli.py "$@"
fi
