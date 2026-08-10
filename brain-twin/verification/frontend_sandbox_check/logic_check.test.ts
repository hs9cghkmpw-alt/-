import test from "node:test";
import assert from "node:assert/strict";

import {
  isDuplicateClientId,
  nextStatusAfterSyncResult,
  planSyncBatch,
  savedMessageFor,
} from "../../apps/web/src/sync/queueLogic.ts";
import { deriveQuietStatus, describeTechnicalStatus } from "../../apps/web/src/utils/quietStatus.ts";
import { isValidUuid, newClientId } from "../../apps/web/src/utils/uuid.ts";
import { findRepoRoot } from "../../apps/web/e2e/helpers/repoRoot.ts";
import path from "node:path";
import { fileURLToPath } from "node:url";

// README.md参照: これは公式テストスイート(apps/web/tests/, Vitest)ではなく、
// 開発時のサンドボックス限定の補助検証である。

function makeRecord(overrides = {}) {
  return {
    clientId: "11111111-1111-4111-8111-111111111111",
    rawText: "牛乳がない",
    inputType: "text",
    capturedAt: "2026-07-30T12:00:00Z",
    syncStatus: "local_only",
    processingStatus: "not_started",
    sourceDevice: "iPhone",
    clientVersion: "1.0.0",
    updatedAt: "2026-07-30T12:00:00Z",
    syncAttemptCount: 0,
    ...overrides,
  };
}

test("planSyncBatch: local_only/queuedが送信対象、syncedは除外", () => {
  const records = [
    makeRecord({ clientId: "a", syncStatus: "local_only" }),
    makeRecord({ clientId: "b", syncStatus: "queued" }),
    makeRecord({ clientId: "c", syncStatus: "synced" }),
  ];
  const plan = planSyncBatch(records, new Date("2026-07-30T13:00:00Z"));
  assert.deepEqual(plan.toSend.map((r) => r.clientId), ["a", "b"]);
  assert.deepEqual(plan.alreadySynced.map((r) => r.clientId), ["c"]);
});

test("planSyncBatch: バックオフ中のsync_failedは送らない", () => {
  const now = new Date("2026-07-30T13:00:00Z");
  const justFailed = makeRecord({
    syncStatus: "sync_failed",
    syncAttemptCount: 1,
    updatedAt: new Date(now.getTime() - 1000).toISOString(),
  });
  const plan = planSyncBatch([justFailed], now, { backoffBaseMs: 3000 });
  assert.equal(plan.toSend.length, 0);
});

test("nextStatusAfterSyncResult: created/already_existsは共にsynced", () => {
  assert.deepEqual(nextStatusAfterSyncResult("queued", "created", 0), { syncStatus: "synced", syncAttemptCount: 0 });
  assert.deepEqual(nextStatusAfterSyncResult("queued", "already_exists", 2), {
    syncStatus: "synced",
    syncAttemptCount: 0,
  });
});

test("isDuplicateClientId: 検出できる", () => {
  const records = [makeRecord({ clientId: "dup-id" })];
  assert.equal(isDuplicateClientId(records, "dup-id"), true);
  assert.equal(isDuplicateClientId(records, "other-id"), false);
});

test("savedMessageFor: 不安を煽る語を含まない", () => {
  assert.doesNotMatch(savedMessageFor(true), /エラー|失敗|未処理/);
  assert.doesNotMatch(savedMessageFor(false), /エラー|失敗|未処理/);
});

test("deriveQuietStatus: PC未接続でも静かな文言", () => {
  const status = deriveQuietStatus({
    pcReachable: false,
    ollamaAvailable: true,
    pendingSyncCount: 3,
    pendingProcessingCount: 0,
  });
  assert.match(status.message, /預けて/);
});

test("describeTechnicalStatus: 詳細画面では数値を含める", () => {
  const text = describeTechnicalStatus({
    pcReachable: true,
    ollamaAvailable: true,
    pendingSyncCount: 84,
    pendingProcessingCount: 3,
  });
  assert.match(text, /84件/);
});

test("newClientId/isValidUuid: 妥当なUUIDを生成し検証できる", () => {
  const id = newClientId();
  assert.equal(isValidUuid(id), true);
  assert.equal(isValidUuid("not-a-uuid"), false);
});

test("findRepoRoot: 監査修正1の再発防止(apps/からでもリポジトリルートへ遡れる)", () => {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const repoRoot = path.resolve(here, "..", "..");
  assert.equal(findRepoRoot(path.join(repoRoot, "apps")), repoRoot);
  assert.equal(findRepoRoot(path.join(repoRoot, "apps", "web", "e2e", "helpers")), repoRoot);
});

test("findRepoRoot: 見つからない場合は分かりやすいエラー", () => {
  assert.throws(() => findRepoRoot("/tmp"), /docker-compose\.test\.yml/);
});
