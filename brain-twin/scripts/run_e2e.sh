#!/usr/bin/env bash
# Brain Twin E2E実行ラッパー (macOS / Linux)
#
# Docker統合テスト環境(docker-compose.test.yml)の起動・Alembic適用・
# Playwright実行・そして成功/失敗にかかわらず確実な後片付け(down -v)までを
# 一貫して行う。本番のdocker-compose.yml・data/には一切触れない。
#
# 【監査修正2】Playwright単体(webServer機能)ではDocker Composeの起動・終了を
# 行わない方針にした(`docker compose up -d`はデタッチして即座に返るため、
# Playwrightのプロセス管理では終了を検知できず、後片付け漏れが起きるため)。
# 代わりにこのスクリプトが一貫してライフサイクルを管理する。
#
# 使い方:
#   ./scripts/run_e2e.sh
#   ./scripts/run_e2e.sh -- pairing.spec.ts   # 特定specだけ実行したい場合
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE="docker compose -f docker-compose.test.yml"

cleanup() {
  local exit_code=$?
  echo "[run_e2e] 後片付け: テスト用コンテナ・ボリュームを削除します"
  $COMPOSE down -v --remove-orphans >/dev/null 2>&1
  exit "$exit_code"
}
trap cleanup EXIT

echo "[run_e2e] Docker統合テスト環境を起動しています..."
if ! $COMPOSE up -d --build; then
  echo "[run_e2e] docker compose up に失敗しました" >&2
  exit 1
fi

echo "[run_e2e] DBスキーマを適用しています..."
MIGRATED=false
for i in $(seq 1 20); do
  if $COMPOSE exec -T server-test alembic upgrade head; then
    MIGRATED=true
    break
  fi
  sleep 2
done
if [ "$MIGRATED" != "true" ]; then
  echo "[run_e2e] alembic upgrade head に失敗しました(serverの起動待ちタイムアウトの可能性)" >&2
  exit 1
fi

echo "[run_e2e] Playwright E2Eを実行しています..."
(cd apps/web && npm run test:e2e -- "$@")
PLAYWRIGHT_EXIT=$?

exit "$PLAYWRIGHT_EXIT"
