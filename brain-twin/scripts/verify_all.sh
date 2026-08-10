#!/usr/bin/env bash
# Brain Twin 一括検証スクリプト (macOS / Linux)
#
# 可能な範囲の検証を1コマンドでまとめて実行し、最後に一目で分かるダッシュボードを
# 表示する。実行日時・環境情報・ログは verification/latest/ に自動保存される
# (失敗時の調査用)。
#
# Ollama・Tailscale・iPhone実機の確認はこのスクリプトの対象外。
#
# 使い方:
#   ./scripts/verify_all.sh
#   ./scripts/verify_all.sh --skip-e2e --skip-docker
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LOG_DIR="$REPO_ROOT/data-test/logs"
mkdir -p "$LOG_DIR"

LATEST_DIR="$REPO_ROOT/verification/latest"
rm -rf "$LATEST_DIR"
mkdir -p "$LATEST_DIR/logs"

SKIP_DOCKER=false
SKIP_E2E=false
for arg in "$@"; do
  case "$arg" in
    --skip-docker) SKIP_DOCKER=true ;;
    --skip-e2e) SKIP_E2E=true ;;
  esac
done

RUN_STARTED_AT="$(date -Iseconds)"

# ==================================================================
# 環境チェック
# ==================================================================
ENV_DOCKER="NG"; ENV_PYTHON="NG"; ENV_NODE="NG"; ENV_OLLAMA="NG"; ENV_TAILSCALE="NG"
command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && ENV_DOCKER="OK"
command -v python3 >/dev/null 2>&1 && ENV_PYTHON="OK"
command -v node >/dev/null 2>&1 && ENV_NODE="OK"
command -v ollama >/dev/null 2>&1 && ENV_OLLAMA="OK"
command -v tailscale >/dev/null 2>&1 && ENV_TAILSCALE="OK"

# 【監査/UAT準備】実行日時・環境情報を verification/latest/ へ保存する。
{
  echo "Brain Twin Verification - 実行環境情報"
  echo "実行日時: $RUN_STARTED_AT"
  echo "OS: $(uname -s) $(uname -r 2>/dev/null || true)"
  echo "Docker    : $ENV_DOCKER $(docker --version 2>/dev/null || true)"
  echo "Python    : $ENV_PYTHON $(python3 --version 2>/dev/null || true)"
  echo "Node.js   : $ENV_NODE $(node --version 2>/dev/null || true)"
  echo "Ollama    : $ENV_OLLAMA $(ollama --version 2>/dev/null || true)"
  echo "Tailscale : $ENV_TAILSCALE $(tailscale version 2>/dev/null | head -1 || true)"
} > "$LATEST_DIR/environment.txt"

declare -a RESULT_NAMES=(); declare -a RESULT_STATUS=(); declare -a RESULT_LOG=()
record() { RESULT_NAMES+=("$1"); RESULT_STATUS+=("$2"); RESULT_LOG+=("$3"); }
section() { echo ""; echo "======================================================"; echo "  $1"; echo "======================================================"; }

# ---------------------------------------------------------------
section "01/10 シェルスクリプト構文チェック"
LOG="$LOG_DIR/01-shell.log"
if bash -n scripts/*.sh > "$LOG" 2>&1; then record "シェルスクリプト構文" "OK" "$LOG"; echo "[OK]"
else record "シェルスクリプト構文" "NG" "$LOG"; echo "[NG] (詳細: $LOG)"; fi

# ---------------------------------------------------------------
section "02/10 Python構文チェック(バックエンド)"
LOG="$LOG_DIR/02-python-syntax.log"
BACKEND_OK=true
if python3 -m py_compile apps/server/app/*.py apps/server/app/routers/*.py apps/server/app/ai/*.py \
    apps/server/app/jobs/*.py apps/server/app/core/*.py apps/server/app/utils/*.py \
    apps/server/alembic/versions/*.py apps/server/scripts/*.py > "$LOG" 2>&1; then
  record "Python構文" "OK" "$LOG"; echo "[OK]"
else
  record "Python構文" "NG" "$LOG"; BACKEND_OK=false; echo "[NG] (詳細: $LOG)"
fi

# ---------------------------------------------------------------
section "03/10 Pythonコアロジック単体テスト(標準ライブラリのみ、依存インストール不要)"
LOG="$LOG_DIR/03-python-tests.log"
{
  (cd apps/server && python3 -m unittest discover -s tests -p "test_core_*.py") 2>&1
  echo "--- cron統合テスト ---"
  (cd apps/server && python3 -m unittest tests.test_cron_scripts_integration) 2>&1
  echo "--- Fake Ollamaサーバーテスト ---"
  (cd testing/fake_ollama && python3 -m unittest test_fake_ollama_server) 2>&1
  echo "--- データモデル(DDL)検証 ---"
  python3 verification/db_schema_check.py 2>&1
} > "$LOG" 2>&1
if grep -q "FAILED\|Traceback\|NG\]" "$LOG"; then
  record "Pythonコアロジック関連テスト" "NG" "$LOG"; BACKEND_OK=false; echo "[NG] (詳細: $LOG)"
else
  record "Pythonコアロジック関連テスト" "OK" "$LOG"; echo "[OK]"
fi

# ---------------------------------------------------------------
section "04/10 バックエンドAPI結合テスト(pytest。未インストールならスキップ)"
LOG="$LOG_DIR/04-pytest.log"
if ! (cd apps/server && python3 -c "import pytest" 2>/dev/null); then
  record "pytest結合テスト" "SKIP" "(pytest未インストール)"
  echo "[SKIP] pytest未インストール"
else
  if (cd apps/server && python3 -m pytest -q) > "$LOG" 2>&1; then
    record "pytest結合テスト" "OK" "$LOG"; echo "[OK]"
  else
    record "pytest結合テスト" "NG" "$LOG"; BACKEND_OK=false; echo "[NG] (詳細: $LOG)"
  fi
fi

# ---------------------------------------------------------------
section "05/10 フロントエンド依存関係の準備(npm ci / npm install)"
LOG="$LOG_DIR/05-npm-install.log"
DEPS_READY=false
FRONTEND_OK=true
NODE_NPM_AVAILABLE=true
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  NODE_NPM_AVAILABLE=false
  record "フロントエンド依存関係の準備" "SKIP" "(Node.js/npmが見つかりません)"
  echo "[SKIP] Node.js/npm未インストール"
else
  (
    cd apps/web
    if [ -f package-lock.json ]; then npm ci; else npm install; fi
  ) > "$LOG" 2>&1
  if [ -d apps/web/node_modules/react ]; then
    DEPS_READY=true
    record "フロントエンド依存関係の準備" "OK" "$LOG"; echo "[OK]"
  else
    record "フロントエンド依存関係の準備" "NG" "$LOG (依存関係インストールに失敗。フロントのテスト/ビルド自体は未実施)"
    FRONTEND_OK=false
    echo "[NG] 依存関係の準備に失敗しました(フロントのテストコード自体の失敗ではありません)。(詳細: $LOG)"
  fi
fi

# ---------------------------------------------------------------
section "06/10 フロントエンド単体テスト(Vitest)"
LOG="$LOG_DIR/06-frontend-test.log"
if [ "$DEPS_READY" != "true" ]; then
  record "フロントエンド単体テスト" "SKIP" "(依存関係未準備)"; echo "[SKIP]"
else
  if (cd apps/web && npm run test) > "$LOG" 2>&1; then
    record "フロントエンド単体テスト" "OK" "$LOG"; echo "[OK]"
  else
    record "フロントエンド単体テスト" "NG" "$LOG"; FRONTEND_OK=false; echo "[NG] (詳細: $LOG)"
  fi
fi

# ---------------------------------------------------------------
section "07/10 フロントエンドビルド"
LOG="$LOG_DIR/07-frontend-build.log"
if [ "$DEPS_READY" != "true" ]; then
  record "フロントエンドビルド" "SKIP" "(依存関係未準備)"; echo "[SKIP]"
else
  if (cd apps/web && npm run build) > "$LOG" 2>&1; then
    record "フロントエンドビルド" "OK" "$LOG"; echo "[OK]"
  else
    record "フロントエンドビルド" "NG" "$LOG"; FRONTEND_OK=false; echo "[NG] (詳細: $LOG)"
  fi
fi

# ---------------------------------------------------------------
section "08/10 Dockerビルド確認"
LOG="$LOG_DIR/08-docker-build.log"
DOCKER_OK=true
DOCKER_RAN=false
if [ "$SKIP_DOCKER" = "true" ]; then
  record "Dockerビルド" "SKIP" "(--skip-docker指定)"; echo "[SKIP]"
elif [ "$ENV_DOCKER" != "OK" ]; then
  record "Dockerビルド" "SKIP" "(dockerが見つかりません)"; echo "[SKIP] Docker未インストール"
else
  DOCKER_RAN=true
  if docker compose build > "$LOG" 2>&1; then
    record "Dockerビルド" "OK" "$LOG"; echo "[OK]"
  else
    record "Dockerビルド" "NG" "$LOG"; DOCKER_OK=false; echo "[NG] (詳細: $LOG)"
  fi
fi

# ---------------------------------------------------------------
section "09/10 Docker統合テスト"
LOG="$LOG_DIR/09-docker-integration.log"
INTEGRATION_STATUS="SKIP"
if [ "$SKIP_DOCKER" = "true" ]; then
  record "Docker統合テスト" "SKIP" "(--skip-docker指定)"; echo "[SKIP]"
elif [ "$ENV_DOCKER" != "OK" ]; then
  record "Docker統合テスト" "SKIP" "(dockerが見つかりません)"; echo "[SKIP] Docker未インストール"
else
  if ./scripts/verify_integration.sh > "$LOG" 2>&1; then
    record "Docker統合テスト" "OK" "$LOG"; INTEGRATION_STATUS="OK"; echo "[OK]"
  else
    CODE=$?
    record "Docker統合テスト" "NG" "$LOG (終了コード: $CODE)"; INTEGRATION_STATUS="NG"
    echo "[NG] 終了コード: $CODE (詳細: $LOG)"
  fi
fi

# ---------------------------------------------------------------
section "10/10 Playwright E2E"
LOG="$LOG_DIR/10-playwright.log"
PLAYWRIGHT_STATUS="SKIP"
if [ "$SKIP_E2E" = "true" ]; then
  record "Playwright E2E" "SKIP" "(--skip-e2e指定)"; echo "[SKIP]"
elif [ "$SKIP_DOCKER" = "true" ] || [ "$ENV_DOCKER" != "OK" ]; then
  record "Playwright E2E" "SKIP" "(Dockerが使えないため)"; echo "[SKIP]"
elif [ "$DEPS_READY" != "true" ] || [ ! -d apps/web/node_modules/@playwright ]; then
  record "Playwright E2E" "SKIP" "(フロントエンド依存関係/Playwrightが未準備)"; echo "[SKIP]"
else
  if ./scripts/run_e2e.sh > "$LOG" 2>&1; then
    record "Playwright E2E" "OK" "$LOG"; PLAYWRIGHT_STATUS="OK"; echo "[OK]"
  else
    CODE=$?
    record "Playwright E2E" "NG" "$LOG (終了コード: $CODE)"; PLAYWRIGHT_STATUS="NG"
    echo "[NG] 終了コード: $CODE (詳細: $LOG)"
  fi
fi

# ==================================================================
# ダッシュボード表示 + verification/latest/ への保存
# ==================================================================
mark() { [ "$1" = "OK" ] && echo "✔" || echo "✖"; }
group_label() {
  # $1: OK/NG/SKIPフラグ, 戻り値表示用
  case "$1" in
    OK) echo "✔ PASS" ;;
    NG) echo "✖ FAIL" ;;
    *) echo "SKIP" ;;
  esac
}

BACKEND_LABEL="✔ PASS"; [ "$BACKEND_OK" = "false" ] && BACKEND_LABEL="✖ FAIL"
if [ "$NODE_NPM_AVAILABLE" != "true" ]; then
  FRONTEND_LABEL="SKIP"
else
  FRONTEND_LABEL="✔ PASS"; [ "$FRONTEND_OK" = "false" ] && FRONTEND_LABEL="✖ FAIL"
fi
if [ "$DOCKER_RAN" != "true" ]; then DOCKER_LABEL="SKIP"; else
  DOCKER_LABEL="✔ PASS"; [ "$DOCKER_OK" = "false" ] && DOCKER_LABEL="✖ FAIL"
fi
INTEGRATION_LABEL="$(group_label "$INTEGRATION_STATUS")"
PLAYWRIGHT_LABEL="$(group_label "$PLAYWRIGHT_STATUS")"

OVERALL="PASS"
if [ "$BACKEND_OK" = "false" ] || [ "$FRONTEND_OK" = "false" ] || \
   { [ "$DOCKER_RAN" = "true" ] && [ "$DOCKER_OK" = "false" ]; } || [ "$INTEGRATION_STATUS" = "NG" ] || [ "$PLAYWRIGHT_STATUS" = "NG" ]; then
  OVERALL="FAIL"
fi

DASHBOARD="$(cat << EOF
==============================
Brain Twin Verification
Environment
$(mark "$ENV_DOCKER") Docker
$(mark "$ENV_PYTHON") Python
$(mark "$ENV_NODE") Node
$(mark "$ENV_OLLAMA") Ollama
$(mark "$ENV_TAILSCALE") Tailscale
Backend
$BACKEND_LABEL
Frontend
$FRONTEND_LABEL
Docker
$DOCKER_LABEL
Integration
$INTEGRATION_LABEL
Playwright
$PLAYWRIGHT_LABEL
Overall
$([ "$OVERALL" = "PASS" ] && echo "✔ PASS" || echo "✖ FAIL")
==============================
EOF
)"

echo ""
echo "$DASHBOARD"

# 詳細一覧(項目ごとのログの場所)も続けて表示する。
echo ""
echo "--- 詳細一覧 ---"
for i in "${!RESULT_NAMES[@]}"; do
  printf "  %-32s %-6s %s\n" "${RESULT_NAMES[$i]}" "${RESULT_STATUS[$i]}" "${RESULT_LOG[$i]}"
done

echo ""
echo "=== 自動検証できるのはここまでです ==="
echo "以下は実機での確認が必要です(このスクリプトの対象外):"
echo "  - 実際のOllama(生成・埋め込み両モデル)との疎通: docker compose exec server python scripts/ollama_preflight.py"
echo "  - Tailscale経由でのiPhoneからの接続: docs/TAILSCALE_SETUP.md / docs/SETUP_IPHONE.md"
echo "  - iPhoneのSafariでのホーム画面追加・実機PWA動作"

# --- verification/latest/ へ保存(監査/UAT準備: 失敗時の調査用) ---
echo "$DASHBOARD" > "$LATEST_DIR/summary.txt"
{
  echo "実行日時(開始): $RUN_STARTED_AT"
  echo "実行日時(終了): $(date -Iseconds)"
  echo ""
  cat "$LATEST_DIR/summary.txt"
} > "$LATEST_DIR/run_info.txt"
cp "$LOG_DIR"/*.log "$LATEST_DIR/logs/" 2>/dev/null || true

echo ""
echo "実行記録を保存しました: $LATEST_DIR/"

if [ "$OVERALL" = "FAIL" ]; then
  exit 1
else
  exit 0
fi
