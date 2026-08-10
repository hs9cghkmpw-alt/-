#!/usr/bin/env bash
# Brain Twin 初回セットアップ (macOS / Linux)
#
# 実行方法:
#   cd brain-twin
#   chmod +x scripts/setup.sh
#   ./scripts/setup.sh
#
# UAT準備: できるだけこのスクリプト1本で環境構築が完結するようにしてある。
# 不足しているものは分かりやすく表示し、自動インストールできないものは
# 理由を表示する。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "== Brain Twin セットアップ =="
echo ""

# ==================================================================
# 環境チェック (Docker / Ollama / Node.js / Python / Tailscale)
# ==================================================================
echo "== 環境チェック =="

ENV_DOCKER="NG"
ENV_OLLAMA="NG"
ENV_NODE="NG"
ENV_PYTHON="NG"
ENV_TAILSCALE="NG"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ENV_DOCKER="OK"
  echo "  ✔ Docker ($(docker --version 2>/dev/null | head -1))"
else
  echo "  ✖ Docker"
fi

if command -v ollama >/dev/null 2>&1; then
  ENV_OLLAMA="OK"
  echo "  ✔ Ollama"
else
  echo "  ✖ Ollama"
fi

if command -v node >/dev/null 2>&1; then
  ENV_NODE="OK"
  echo "  ✔ Node.js ($(node --version 2>/dev/null))  [Brain Twin本体には不要。scripts/verify_all.sh でのみ使用]"
else
  echo "  ✖ Node.js  [Brain Twin本体には不要。scripts/verify_all.sh でのみ使用]"
fi

if command -v python3 >/dev/null 2>&1; then
  ENV_PYTHON="OK"
  echo "  ✔ Python ($(python3 --version 2>/dev/null))  [Brain Twin本体には不要。scripts/verify_all.sh でのみ使用]"
else
  echo "  ✖ Python  [Brain Twin本体には不要。scripts/verify_all.sh でのみ使用]"
fi

if command -v tailscale >/dev/null 2>&1; then
  ENV_TAILSCALE="OK"
  echo "  ✔ Tailscale  [iPhoneから使う場合に必要。PCのみで試す場合は後回しでよい]"
else
  echo "  ✖ Tailscale  [iPhoneから使う場合に必要。PCのみで試す場合は後回しでよい]"
fi

echo ""

# --- Docker: 自動インストール不可(GUIインストーラ・管理者権限・再起動が必要なため) ---
if [ "$ENV_DOCKER" = "NG" ]; then
  echo "[必須] Dockerが見つかりません。自動インストールはできません"
  echo "       (理由: Docker DesktopはGUIインストーラと管理者権限、場合によっては再起動が必要なため)。"
  echo "       以下から手動でインストールしてください:"
  echo "         https://www.docker.com/products/docker-desktop/"
  echo ""
  echo "Dockerのインストール後、このスクリプトを再実行してください。"
  exit 1
fi

# --- Ollama: 既知のパッケージマネージャがあれば、確認の上で自動インストールを試みる ---
if [ "$ENV_OLLAMA" = "NG" ]; then
  echo "[推奨] Ollamaが見つかりません。AI整理機能を使うために必要です"
  echo "       (無くてもBrain Twin自体は起動・入力・保存・検索が可能です)。"
  AUTO_INSTALLED=false
  if command -v brew >/dev/null 2>&1; then
    read -r -p "       Homebrewで 'brew install ollama' を今すぐ実行しますか? [y/N]: " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
      brew install ollama && AUTO_INSTALLED=true
    fi
  elif command -v curl >/dev/null 2>&1 && [ "$(uname -s)" = "Linux" ]; then
    read -r -p "       公式インストールスクリプト(curl -fsSL https://ollama.com/install.sh | sh)を今すぐ実行しますか? [y/N]: " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
      curl -fsSL https://ollama.com/install.sh | sh && AUTO_INSTALLED=true
    fi
  fi
  if [ "$AUTO_INSTALLED" != "true" ]; then
    echo "       自動インストールを行いませんでした(理由: パッケージマネージャが無いか、確認で見送られたため)。"
    echo "       手動でインストールする場合: https://ollama.com/download"
  fi
  echo ""
fi

# --- Tailscale: Docker同様、GUI/管理者権限が絡むため自動インストールは行わない ---
if [ "$ENV_TAILSCALE" = "NG" ]; then
  echo "[任意] Tailscaleが見つかりません。iPhoneから使う場合に必要です(PCのみで試す間は不要)。"
  echo "       自動インストールはできません(理由: OSごとのインストーラとサインインが必要なため)。"
  echo "       手動でインストールする場合: https://tailscale.com/download"
  echo ""
fi

if [ "$ENV_NODE" = "NG" ] || [ "$ENV_PYTHON" = "NG" ]; then
  echo "[情報] Node.js/PythonはBrain Twin本体の動作自体には不要です"
  echo "       (Dockerコンテナ内で完結するため)。scripts/verify_all.sh で追加のテストを"
  echo "       ホストPC上でも実行したい場合にのみ、以下からインストールしてください:"
  [ "$ENV_NODE" = "NG" ] && echo "         Node.js: https://nodejs.org"
  [ "$ENV_PYTHON" = "NG" ] && echo "         Python : https://www.python.org/downloads/"
  echo ""
fi

# ==================================================================
# 本セットアップ
# ==================================================================

# --- .env の準備 ---
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[OK] .env を作成しました(.env.exampleからコピー)。必要に応じて内容を編集してください。"
else
  echo "[SKIP] .env は既に存在します。"
fi

mkdir -p data/database data/backups data/exports
echo "[OK] data/ ディレクトリを準備しました。"

# --- Ollamaモデルの確認 (ホスト側Ollamaがインストール済みの場合) ---
if command -v ollama >/dev/null 2>&1; then
  MISSING_MODELS=""
  if ! ollama list 2>/dev/null | grep -q "qwen2.5"; then
    MISSING_MODELS="${MISSING_MODELS} qwen2.5:7b-instruct"
  fi
  if ! ollama list 2>/dev/null | grep -q "bge-m3"; then
    MISSING_MODELS="${MISSING_MODELS} bge-m3"
  fi
  if [ -n "$MISSING_MODELS" ]; then
    echo "[INFO] 以下のモデルがまだ無いようです。後で以下を実行してください:"
    for m in $MISSING_MODELS; do
      echo "    ollama pull $m"
    done
  fi
else
  echo "[INFO] Docker内でOllamaを動かす場合は次のように起動してください:"
  echo "          docker compose --profile dockerized-ollama up -d ollama"
  echo "          docker compose exec ollama ollama pull qwen2.5:7b-instruct"
  echo "          docker compose exec ollama ollama pull bge-m3"
  echo "          (.envのOLLAMA_BASE_URLも http://ollama:11434 に変更してください)"
fi

# --- ビルド & 起動 ---
echo "== Dockerイメージをビルドしています(初回は数分かかります) =="
docker compose build

echo "== コンテナを起動しています =="
docker compose up -d

echo "== DBスキーマを最新化しています =="
docker compose exec -T server alembic upgrade head

# --- Ollama事前診断 ---
# 診断は情報提供のみが目的で、失敗してもセットアップ自体は続行する
# (仕様書13: モデル未導入でもアプリは起動・入力・保存・検索が可能)。
echo "== Ollama事前診断(参考情報。失敗してもセットアップは続行します) =="
docker compose exec -T server python scripts/ollama_preflight.py || true

echo "== ヘルスチェック =="
WEB_PORT="$(grep -E '^WEB_PORT=' .env | cut -d= -f2 || echo 8080)"
WEB_PORT="${WEB_PORT:-8080}"
for i in $(seq 1 15); do
  if curl -sf "http://127.0.0.1:${WEB_PORT}/api/health" >/dev/null 2>&1; then
    echo "[OK] サーバーが起動しました (http://127.0.0.1:${WEB_PORT} 経由、/api はNginxがserverへ内部転送)"
    break
  fi
  sleep 1
  if [ "$i" -eq 15 ]; then
    echo "[警告] サーバーの起動確認がタイムアウトしました。'docker compose logs server' と 'docker compose logs web' を確認してください。"
  fi
done

echo ""
echo "== 次のステップ: iPhoneとのペアリング =="
echo "以下を実行すると、iPhoneで入力する『ペアリングコード』が発行されます:"
echo "(このコマンドはPC上でのみ実行できます。Web経由の公開エンドポイントには存在しません)"
echo ""
echo "    docker compose exec server curl -s -X POST http://localhost:8000/api/pairing/start"
echo ""
echo "表示された 'code' を、iPhoneのBrain Twin(ホーム画面に追加後)で入力してください。"
echo "iPhone側で開くアドレスは http://127.0.0.1:${WEB_PORT} と同じ経路(tailscale serveで公開したURL)です。"
echo "詳しい手順は docs/SETUP_IPHONE.md と docs/TAILSCALE_SETUP.md を参照してください。"
echo ""
echo "セットアップはここまでです。お疲れさまでした。"
