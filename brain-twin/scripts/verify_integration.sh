#!/usr/bin/env bash
# Brain Twin Docker統合テスト (macOS / Linux)
#
# docker-compose.test.yml を使い、本番データ(data/, docker-compose.yml)には
# 一切触れずに、Nginx同一オリジン経由のAPI疎通・ペアリング・同期冪等性・検索・
# フィードバック・Ollama停止/復帰・バックアップ/復元までを自動検証する。
#
# 使い方:
#   ./scripts/verify_integration.sh
#
# 終了コードで失敗段階が分かる(下記STAGE定義参照)。成功・失敗にかかわらず、
# 最後に必ず `docker compose -f docker-compose.test.yml down -v` で後片付けする。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE="docker compose -f docker-compose.test.yml"
WEB_PORT="${TEST_WEB_PORT:-18080}"
OLLAMA_PORT="${TEST_OLLAMA_PORT:-11435}"
BASE_URL="http://127.0.0.1:${WEB_PORT}"
FAKE_OLLAMA_URL="http://127.0.0.1:${OLLAMA_PORT}"
LOG_FILE="$REPO_ROOT/data-test/integration_test.log"
mkdir -p "$REPO_ROOT/data-test"

# --- 段階定義(終了コード) ---
declare -A STAGE_CODE=(
  [build]=10 [up]=11 [migrate]=12 [nginx_syntax]=13 [health]=14
  [pairing_start_blocked]=15 [pairing_start_internal]=16 [pairing_complete]=17
  [capture_sync]=18 [idempotency]=19 [search]=20 [feedback]=21
  [ollama_down]=22 [ollama_recovery]=23 [backup]=24 [restore]=25
)
CURRENT_STAGE="init"
PASSED_STAGES=()

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG_FILE"; }

cleanup() {
  local exit_code=$?
  log "後片付け: テスト用コンテナ・ボリュームを削除します"
  $COMPOSE down -v --remove-orphans >>"$LOG_FILE" 2>&1
  if [ "$exit_code" -eq 0 ]; then
    log "=== 統合テスト成功 (全段階パス: ${PASSED_STAGES[*]}) ==="
  else
    log "=== 統合テスト失敗: 段階 '${CURRENT_STAGE}' (終了コード ${exit_code}) ==="
    log "詳細ログ: $LOG_FILE"
  fi
  exit "$exit_code"
}
trap cleanup EXIT

fail() {
  local stage="$1"; shift
  CURRENT_STAGE="$stage"
  log "[失敗] 段階 '$stage': $*"
  exit "${STAGE_CODE[$stage]:-99}"
}

pass_stage() {
  PASSED_STAGES+=("$1")
  log "[OK] 段階 '$1' 完了"
}

require_json_field() {
  # require_json_field '<json>' '<キー>' -> pythonでフィールド抽出(jq依存を避ける)
  python3 -c "
import json, sys
data = json.loads(sys.argv[1])
keys = sys.argv[2].split('.')
cur = data
for k in keys:
    cur = cur[k]
print(cur)
" "$1" "$2" 2>/dev/null
}

log "=== Brain Twin Docker統合テスト 開始 ==="
log "Web(同一オリジン): $BASE_URL / Fake Ollama制御: $FAKE_OLLAMA_URL"

# --- Stage: build ---
CURRENT_STAGE="build"
if ! $COMPOSE build >>"$LOG_FILE" 2>&1; then
  fail build "docker compose build に失敗しました"
fi
pass_stage build

# --- Stage: up ---
CURRENT_STAGE="up"
if ! $COMPOSE up -d >>"$LOG_FILE" 2>&1; then
  fail up "docker compose up に失敗しました"
fi
pass_stage up

# --- Stage: migrate ---
CURRENT_STAGE="migrate"
MIGRATED=false
for i in $(seq 1 20); do
  if $COMPOSE exec -T server-test alembic upgrade head >>"$LOG_FILE" 2>&1; then
    MIGRATED=true
    break
  fi
  sleep 2
done
if [ "$MIGRATED" != "true" ]; then
  fail migrate "alembic upgrade head に失敗しました(serverの起動待ちタイムアウトの可能性)"
fi
pass_stage migrate

# --- Stage: nginx_syntax ---
CURRENT_STAGE="nginx_syntax"
if ! $COMPOSE exec -T web-test nginx -t >>"$LOG_FILE" 2>&1; then
  fail nginx_syntax "nginx -t が失敗しました(nginx.confの構文エラーの可能性)"
fi
pass_stage nginx_syntax

# --- Stage: health (同一オリジン経由) ---
CURRENT_STAGE="health"
HEALTH_OK=false
HEALTH_BODY=""
for i in $(seq 1 20); do
  HEALTH_BODY="$(curl -sf "$BASE_URL/api/health" 2>>"$LOG_FILE")" && { HEALTH_OK=true; break; }
  sleep 1
done
if [ "$HEALTH_OK" != "true" ]; then
  fail health "GET $BASE_URL/api/health に失敗しました"
fi
# Content-Typeと構造の検証(単にHTTP 200だけでなく、SPAのindex.htmlが返っていないことも確認)
CONTENT_TYPE="$(curl -sf -D - -o /dev/null "$BASE_URL/api/health" | grep -i '^content-type' | tr -d '\r')"
if ! echo "$CONTENT_TYPE" | grep -qi "application/json"; then
  fail health "Content-TypeがJSONではありません: $CONTENT_TYPE (SPAのindex.htmlが返っている可能性)"
fi
STATUS_FIELD="$(require_json_field "$HEALTH_BODY" "status")"
if [ "$STATUS_FIELD" != "ok" ]; then
  fail health "healthレスポンスのstatusが'ok'ではありません: $HEALTH_BODY"
fi
if echo "$HEALTH_BODY" | grep -q "<!doctype\|<html"; then
  fail health "JSONではなくHTMLが返っています(SPAフォールバックに巻き込まれている可能性)"
fi
pass_stage health

# --- Stage: pairing_start_blocked (公開経路で403になること) ---
CURRENT_STAGE="pairing_start_blocked"
BLOCKED_STATUS="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/pairing/start")"
if [ "$BLOCKED_STATUS" != "403" ]; then
  fail pairing_start_blocked "公開経路の/api/pairing/startが403ではありません(実際: $BLOCKED_STATUS)。Nginxのedgeブロックが機能していない可能性"
fi
pass_stage pairing_start_blocked

# --- Stage: pairing_start_internal (docker exec経由なら成功すること) ---
CURRENT_STAGE="pairing_start_internal"
PAIRING_START_BODY="$($COMPOSE exec -T server-test curl -sf -X POST http://localhost:8000/api/pairing/start 2>>"$LOG_FILE")"
if [ -z "$PAIRING_START_BODY" ]; then
  fail pairing_start_internal "コンテナ内部からの/api/pairing/start呼び出しに失敗しました"
fi
PAIRING_CODE="$(require_json_field "$PAIRING_START_BODY" "code")"
if [ -z "$PAIRING_CODE" ]; then
  fail pairing_start_internal "ペアリングコードが取得できませんでした: $PAIRING_START_BODY"
fi
log "発行されたペアリングコード: $PAIRING_CODE"
pass_stage pairing_start_internal

# --- Stage: pairing_complete (公開経路=同一オリジン経由で完了できること) ---
CURRENT_STAGE="pairing_complete"
COMPLETE_BODY="$(curl -sf -X POST "$BASE_URL/api/pairing/complete" \
  -H "Content-Type: application/json" \
  -d "{\"code\":\"$PAIRING_CODE\",\"device_name\":\"integration-test\"}" 2>>"$LOG_FILE")"
DEVICE_TOKEN="$(require_json_field "$COMPLETE_BODY" "device_token")"
if [ -z "$DEVICE_TOKEN" ]; then
  fail pairing_complete "端末トークンが取得できませんでした: $COMPLETE_BODY"
fi

# 不正なコードでは安全に失敗すること(400系)も確認する。
BAD_CODE_STATUS="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/pairing/complete" \
  -H "Content-Type: application/json" -d '{"code":"WRONGCODE","device_name":"x"}')"
if [ "$BAD_CODE_STATUS" -lt 400 ]; then
  fail pairing_complete "不正なコードが受理されてしまいました(status: $BAD_CODE_STATUS)"
fi
pass_stage pairing_complete

AUTH_HEADER="Authorization: Bearer $DEVICE_TOKEN"

# --- Stage: capture_sync (Authorizationヘッダが正しくFastAPIまで届くこと含む) ---
CURRENT_STAGE="capture_sync"
CLIENT_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
CAPTURE_BODY="$(curl -sf -X POST "$BASE_URL/api/captures" \
  -H "Content-Type: application/json" -H "$AUTH_HEADER" \
  -d "{\"client_id\":\"$CLIENT_ID\",\"raw_text\":\"統合テスト用の思考です\",\"input_type\":\"text\",\"captured_at\":\"2026-07-30T21:00:00Z\"}" 2>>"$LOG_FILE")"
CAPTURE_ID="$(require_json_field "$CAPTURE_BODY" "id")"
if [ -z "$CAPTURE_ID" ]; then
  fail capture_sync "capture作成に失敗しました(Authorizationヘッダが転送されていない可能性): $CAPTURE_BODY"
fi
pass_stage capture_sync

# --- Stage: idempotency (同一client_id再送で重複しないこと) ---
CURRENT_STAGE="idempotency"
CAPTURE_BODY2="$(curl -sf -X POST "$BASE_URL/api/captures" \
  -H "Content-Type: application/json" -H "$AUTH_HEADER" \
  -d "{\"client_id\":\"$CLIENT_ID\",\"raw_text\":\"統合テスト用の思考です\",\"input_type\":\"text\",\"captured_at\":\"2026-07-30T21:00:00Z\"}" 2>>"$LOG_FILE")"
CAPTURE_ID2="$(require_json_field "$CAPTURE_BODY2" "id")"
if [ "$CAPTURE_ID" != "$CAPTURE_ID2" ]; then
  fail idempotency "同一client_idの再送で異なるIDが返りました(重複作成): $CAPTURE_ID vs $CAPTURE_ID2"
fi
LIST_BODY="$(curl -sf "$BASE_URL/api/captures?range=all" -H "$AUTH_HEADER")"
MATCH_COUNT="$(python3 -c "
import json, sys
data = json.loads(sys.argv[1])
print(sum(1 for c in data['items'] if c['client_id'] == sys.argv[2]))
" "$LIST_BODY" "$CLIENT_ID")"
if [ "$MATCH_COUNT" != "1" ]; then
  fail idempotency "一覧に同一client_idのcaptureが1件ではありません(実際: $MATCH_COUNT件)"
fi
pass_stage idempotency

# --- Stage: search (監査修正3: 単なるJSON妥当性チェックではなく実質的な検証にする) ---
CURRENT_STAGE="search"
SEARCH_UNIQUE_TEXT="検索専用固有文言$(date +%s)"
curl -sf -X POST "$FAKE_OLLAMA_URL/_control/config" -H "Content-Type: application/json" \
  -d "{\"chat_content\": \"{\\\"thoughts\\\":[{\\\"content\\\":\\\"${SEARCH_UNIQUE_TEXT}\\\",\\\"types\\\":[\\\"thought\\\"]}]}\"}" >>"$LOG_FILE" 2>&1

SEARCH_CLIENT_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
SEARCH_CAPTURE_BODY="$(curl -sf -X POST "$BASE_URL/api/captures" \
  -H "Content-Type: application/json" -H "$AUTH_HEADER" \
  -d "{\"client_id\":\"$SEARCH_CLIENT_ID\",\"raw_text\":\"$SEARCH_UNIQUE_TEXT\",\"input_type\":\"text\",\"captured_at\":\"2026-07-30T21:00:00Z\"}" 2>>"$LOG_FILE")"
SEARCH_CAPTURE_ID="$(require_json_field "$SEARCH_CAPTURE_BODY" "id")"
if [ -z "$SEARCH_CAPTURE_ID" ]; then
  fail search "検索用captureの作成に失敗しました: $SEARCH_CAPTURE_BODY"
fi

# 1. AI処理(Fake Ollama)が完了するまでポーリングする。時間内に完了しなければ失敗させる。
SEARCH_PROCESSED=false
for i in $(seq 1 15); do
  STATUS_BODY="$(curl -sf "$BASE_URL/api/captures/$SEARCH_CAPTURE_ID" -H "$AUTH_HEADER" 2>>"$LOG_FILE")"
  if [ "$(require_json_field "$STATUS_BODY" "processing_status")" = "done" ]; then
    SEARCH_PROCESSED=true
    break
  fi
  sleep 2
done
if [ "$SEARCH_PROCESSED" != "true" ]; then
  fail search "検索用の思考がタイムアウトまでに処理完了(done)になりませんでした"
fi

SEARCH_THOUGHTS_BODY="$(curl -sf "$BASE_URL/api/thoughts?capture_id=$SEARCH_CAPTURE_ID" -H "$AUTH_HEADER")"
SEARCH_THOUGHT_ID="$(python3 -c "
import json, sys
data = json.loads(sys.argv[1])
print(data['items'][0]['id'] if data['items'] else '')
" "$SEARCH_THOUGHTS_BODY")"
if [ -z "$SEARCH_THOUGHT_ID" ]; then
  fail search "処理完了のはずなのにthoughtが1件も見つかりません"
fi

# 2. 固有語で検索し、対象thoughtのID・内容が一致することを確認する(単なるJSON妥当性ではない)。
SEARCH_RESULT="$(curl -sf --data-urlencode "q=$SEARCH_UNIQUE_TEXT" -G "$BASE_URL/api/search" -H "$AUTH_HEADER")"
SEARCH_MATCH="$(python3 -c "
import json, sys
data = json.loads(sys.argv[1])
target_id, target_content = sys.argv[2], sys.argv[3]
for hit in data.get('thoughts', []):
    if hit['thought']['id'] == target_id and hit['thought']['content'] == target_content:
        print('yes'); sys.exit()
print('no')
" "$SEARCH_RESULT" "$SEARCH_THOUGHT_ID" "$SEARCH_UNIQUE_TEXT")"
if [ "$SEARCH_MATCH" != "yes" ]; then
  fail search "固有文言での検索結果に、期待するID・内容の思考が含まれていません: $SEARCH_RESULT"
fi

# 3. 無関係な固有語では対象が含まれないことを確認する(0件でもPASSにしていた旧バグの防止)。
UNRELATED_WORD="全く無関係な固有文言$(date +%s)XYZ"
UNRELATED_RESULT="$(curl -sf --data-urlencode "q=$UNRELATED_WORD" -G "$BASE_URL/api/search" -H "$AUTH_HEADER")"
UNRELATED_MATCH="$(python3 -c "
import json, sys
data = json.loads(sys.argv[1])
target_id = sys.argv[2]
for hit in data.get('thoughts', []):
    if hit['thought']['id'] == target_id:
        print('yes'); sys.exit()
print('no')
" "$UNRELATED_RESULT" "$SEARCH_THOUGHT_ID")"
if [ "$UNRELATED_MATCH" = "yes" ]; then
  fail search "無関係な語での検索結果に対象の思考が含まれてしまっています(誤検出)"
fi
pass_stage search

# --- Stage: feedback (監査修正4: thought未作成でのスキップ成功を禁止し、DBへの実反映まで確認する) ---
CURRENT_STAGE="feedback"

# 1. フィードバック対象・比較対象(誤って別thoughtを汚染しないことの確認用)の2つのthoughtを用意する。
#    thoughtが作成されるまで一定時間ポーリングし、時間内に作成されなければ統合試験自体を失敗させる
#    (以前は「thoughtが無ければ疎通確認のみでPASS」としていたが、これを禁止する)。
FEEDBACK_TARGET_TEXT="フィードバック対象$(date +%s)"
curl -sf -X POST "$FAKE_OLLAMA_URL/_control/config" -H "Content-Type: application/json" \
  -d "{\"chat_content\": \"{\\\"thoughts\\\":[{\\\"content\\\":\\\"${FEEDBACK_TARGET_TEXT}\\\",\\\"types\\\":[\\\"thought\\\"]}]}\"}" >>"$LOG_FILE" 2>&1
FB_CLIENT_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
FB_CAPTURE_BODY="$(curl -sf -X POST "$BASE_URL/api/captures" -H "Content-Type: application/json" -H "$AUTH_HEADER" \
  -d "{\"client_id\":\"$FB_CLIENT_ID\",\"raw_text\":\"$FEEDBACK_TARGET_TEXT\",\"input_type\":\"text\",\"captured_at\":\"2026-07-30T21:00:00Z\"}")"
FB_CAPTURE_ID="$(require_json_field "$FB_CAPTURE_BODY" "id")"

FEEDBACK_OTHER_TEXT="フィードバック非対象$(date +%s)"
curl -sf -X POST "$FAKE_OLLAMA_URL/_control/config" -H "Content-Type: application/json" \
  -d "{\"chat_content\": \"{\\\"thoughts\\\":[{\\\"content\\\":\\\"${FEEDBACK_OTHER_TEXT}\\\",\\\"types\\\":[\\\"thought\\\"]}]}\"}" >>"$LOG_FILE" 2>&1
FB_OTHER_CLIENT_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
FB_OTHER_CAPTURE_BODY="$(curl -sf -X POST "$BASE_URL/api/captures" -H "Content-Type: application/json" -H "$AUTH_HEADER" \
  -d "{\"client_id\":\"$FB_OTHER_CLIENT_ID\",\"raw_text\":\"$FEEDBACK_OTHER_TEXT\",\"input_type\":\"text\",\"captured_at\":\"2026-07-30T21:00:00Z\"}")"
FB_OTHER_CAPTURE_ID="$(require_json_field "$FB_OTHER_CAPTURE_BODY" "id")"

FB_THOUGHT_ID=""
FB_OTHER_THOUGHT_ID=""
for i in $(seq 1 15); do
  T1="$(curl -sf "$BASE_URL/api/thoughts?capture_id=$FB_CAPTURE_ID" -H "$AUTH_HEADER" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['items'][0]['id'] if d['items'] else '')")"
  T2="$(curl -sf "$BASE_URL/api/thoughts?capture_id=$FB_OTHER_CAPTURE_ID" -H "$AUTH_HEADER" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['items'][0]['id'] if d['items'] else '')")"
  if [ -n "$T1" ] && [ -n "$T2" ]; then
    FB_THOUGHT_ID="$T1"
    FB_OTHER_THOUGHT_ID="$T2"
    break
  fi
  sleep 2
done
if [ -z "$FB_THOUGHT_ID" ] || [ -z "$FB_OTHER_THOUGHT_ID" ]; then
  fail feedback "タイムアウトまでにフィードバック検証用のthoughtが作成されませんでした(スキップして成功扱いにすることは禁止)"
fi

# 2. feedback APIが期待するHTTPステータスを返すこと
FEEDBACK_STATUS="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/thoughts/$FB_THOUGHT_ID/feedback" \
  -H "Content-Type: application/json" -H "$AUTH_HEADER" -d '{"event_type":"marked_important"}')"
if [ "$FEEDBACK_STATUS" != "201" ]; then
  fail feedback "フィードバックAPIが期待するステータス(201)を返しませんでした(実際: $FEEDBACK_STATUS)"
fi

# 3. feedback_eventsへ実際に保存されていることを、DBを直接確認して検証する(APIの応答だけで満足しない)。
FB_DB_COUNT="$($COMPOSE exec -T server-test python3 -c "
import sqlite3
con = sqlite3.connect('/app/data/database/brain_twin.sqlite3')
row = con.execute(\"SELECT COUNT(*) FROM feedback_events WHERE thought_id=? AND event_type='marked_important'\", ('$FB_THOUGHT_ID',)).fetchone()
print(row[0])
" 2>>"$LOG_FILE" | tr -d '\r')"
if [ "${FB_DB_COUNT:-0}" -lt 1 ]; then
  fail feedback "feedback_eventsテーブルに記録が見つかりません(APIは成功を返したがDBへ反映されていません)"
fi

# 4. 別thoughtへ誤って保存されない(意図した思考にだけ効果が及ぶ)ことを確認する。
FB_OTHER_IMPORTANCE_BEFORE="$(curl -sf "$BASE_URL/api/thoughts/$FB_OTHER_THOUGHT_ID" -H "$AUTH_HEADER" | python3 -c "import json,sys; print(json.load(sys.stdin).get('importance'))")"
if [ "$FB_OTHER_IMPORTANCE_BEFORE" != "None" ]; then
  fail feedback "対象外のthoughtのimportanceが、フィードバック前から既に変化しています(テスト前提が崩れています)"
fi
FB_OTHER_DB_COUNT="$($COMPOSE exec -T server-test python3 -c "
import sqlite3
con = sqlite3.connect('/app/data/database/brain_twin.sqlite3')
row = con.execute('SELECT COUNT(*) FROM feedback_events WHERE thought_id=?', ('$FB_OTHER_THOUGHT_ID',)).fetchone()
print(row[0])
" 2>>"$LOG_FILE" | tr -d '\r')"
if [ "${FB_OTHER_DB_COUNT:-0}" -ne 0 ]; then
  fail feedback "対象外のthoughtにフィードバックが誤って記録されています(別thoughtへの汚染)"
fi

# 5. 同じ操作を二重送信した場合、仕様どおり(履歴として2件記録され、状態は一貫したまま)であることを確認する。
curl -s -o /dev/null -X POST "$BASE_URL/api/thoughts/$FB_THOUGHT_ID/feedback" \
  -H "Content-Type: application/json" -H "$AUTH_HEADER" -d '{"event_type":"marked_important"}'
FB_DB_COUNT_AFTER_DUP="$($COMPOSE exec -T server-test python3 -c "
import sqlite3
con = sqlite3.connect('/app/data/database/brain_twin.sqlite3')
row = con.execute(\"SELECT COUNT(*) FROM feedback_events WHERE thought_id=? AND event_type='marked_important'\", ('$FB_THOUGHT_ID',)).fetchone()
print(row[0])
" 2>>"$LOG_FILE" | tr -d '\r')"
if [ "${FB_DB_COUNT_AFTER_DUP:-0}" -ne 2 ]; then
  fail feedback "二重送信後の履歴件数が期待(2件)と異なります(実際: $FB_DB_COUNT_AFTER_DUP)"
fi
FB_IMPORTANCE_AFTER_DUP="$(curl -sf "$BASE_URL/api/thoughts/$FB_THOUGHT_ID" -H "$AUTH_HEADER" | python3 -c "import json,sys; print(json.load(sys.stdin).get('importance'))")"
if [ "$FB_IMPORTANCE_AFTER_DUP" != "1.0" ]; then
  fail feedback "二重送信後もimportanceは1.0のまま一貫しているはずですが、実際: $FB_IMPORTANCE_AFTER_DUP"
fi
pass_stage feedback

# --- Stage: ollama_down (Fake Ollamaを止めても保存・検索は動くこと) ---
CURRENT_STAGE="ollama_down"
$COMPOSE stop fake-ollama-test >>"$LOG_FILE" 2>&1
sleep 1
DOWN_CLIENT_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
DOWN_CAPTURE_BODY="$(curl -sf -X POST "$BASE_URL/api/captures" \
  -H "Content-Type: application/json" -H "$AUTH_HEADER" \
  -d "{\"client_id\":\"$DOWN_CLIENT_ID\",\"raw_text\":\"Ollama停止中の思考\",\"input_type\":\"text\",\"captured_at\":\"2026-07-30T21:00:00Z\"}" 2>>"$LOG_FILE")"
DOWN_CAPTURE_ID="$(require_json_field "$DOWN_CAPTURE_BODY" "id")"
if [ -z "$DOWN_CAPTURE_ID" ]; then
  fail ollama_down "Ollama停止中にcaptureの保存自体が失敗しました(仕様書13違反)"
fi
DOWN_SEARCH_BODY="$(curl -sf "$BASE_URL/api/search?q=Ollama停止中" -H "$AUTH_HEADER")"
if ! echo "$DOWN_SEARCH_BODY" | grep -q "$DOWN_CAPTURE_ID"; then
  fail ollama_down "Ollama停止中に検索結果からcaptureが見つかりませんでした"
fi
pass_stage ollama_down

# --- Stage: ollama_recovery (再起動後、再処理でthoughtが作られること) ---
CURRENT_STAGE="ollama_recovery"
$COMPOSE start fake-ollama-test >>"$LOG_FILE" 2>&1
sleep 2
curl -sf -X POST "$FAKE_OLLAMA_URL/_control/reset" >>"$LOG_FILE" 2>&1 || true
RETRY_STATUS="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/processing/$DOWN_CAPTURE_ID/retry" -H "$AUTH_HEADER")"
if [ "$RETRY_STATUS" != "202" ]; then
  fail ollama_recovery "再処理リクエストが失敗しました(status: $RETRY_STATUS)"
fi

RECOVERED=false
for i in $(seq 1 15); do
  sleep 2
  CAP_STATUS_BODY="$(curl -sf "$BASE_URL/api/captures/$DOWN_CAPTURE_ID" -H "$AUTH_HEADER")"
  PSTATUS="$(require_json_field "$CAP_STATUS_BODY" "processing_status")"
  if [ "$PSTATUS" = "done" ]; then
    RECOVERED=true
    break
  fi
done
if [ "$RECOVERED" != "true" ]; then
  fail ollama_recovery "Ollama復帰後もcaptureのprocessing_statusが'done'になりませんでした(最終状態: $PSTATUS)"
fi
# 原文が変更されていないことを確認(仕様書3-11)
ORIG_TEXT="$(require_json_field "$CAP_STATUS_BODY" "raw_text")"
if [ "$ORIG_TEXT" != "Ollama停止中の思考" ]; then
  fail ollama_recovery "原文が変更されています(あってはならない): $ORIG_TEXT"
fi
pass_stage ollama_recovery

# --- Stage: backup ---
CURRENT_STAGE="backup"
BACKUP_STATUS="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/backup" -H "$AUTH_HEADER")"
if [ "$BACKUP_STATUS" != "200" ]; then
  fail backup "バックアップAPIが失敗しました(status: $BACKUP_STATUS)"
fi
BACKUP_COUNT="$(ls -1 "$REPO_ROOT/data-test/backups"/*.sqlite3 2>/dev/null | wc -l | tr -d ' ')"
if [ "$BACKUP_COUNT" -lt 1 ]; then
  fail backup "バックアップファイルがdata-test/backups/に作成されていません"
fi
pass_stage backup

# --- Stage: restore ---
CURRENT_STAGE="restore"
LATEST_BACKUP="$(ls -t "$REPO_ROOT/data-test/backups"/*.sqlite3 | head -1)"
LATEST_BACKUP_NAME="$(basename "$LATEST_BACKUP")"
if ! $COMPOSE exec -T server-test python scripts/restore_cli.py --file "$LATEST_BACKUP_NAME" --yes >>"$LOG_FILE" 2>&1; then
  fail restore "復元スクリプトの実行に失敗しました"
fi
$COMPOSE restart server-test >>"$LOG_FILE" 2>&1
sleep 3
POST_RESTORE_HEALTH="$(curl -sf "$BASE_URL/api/health" 2>>"$LOG_FILE")"
if [ -z "$POST_RESTORE_HEALTH" ]; then
  fail restore "復元後にサーバーが正常に再起動しませんでした"
fi
pass_stage restore

log "=== すべての段階が成功しました ==="
exit 0
