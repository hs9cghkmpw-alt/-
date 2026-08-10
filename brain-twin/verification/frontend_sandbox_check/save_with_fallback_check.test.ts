import test from "node:test";
import assert from "node:assert/strict";

import { saveWithRetryAndFallback, recoverWithRetry } from "../../apps/web/src/db/saveWithFallback.ts";

// README.md参照: これは公式テストスイート(apps/web/tests/, Vitest)ではなく、
// 開発時のサンドボックス限定の補助検証である。対象ロジックはVitest版と共通。

function makeRecord(overrides = {}) {
  return {
    clientId: "11111111-1111-4111-8111-111111111111",
    rawText: "今日はもう無理。",
    inputType: "text",
    capturedAt: "2026-08-01T12:00:00Z",
    syncStatus: "local_only",
    processingStatus: "not_started",
    sourceDevice: "iPhone",
    clientVersion: "0.1.0",
    updatedAt: "2026-08-01T12:00:00Z",
    syncAttemptCount: 0,
    ...overrides,
  };
}

function makeDeps(overrides = {}) {
  let fallback = [];
  const calls = { put: [], writeFallback: [], sleep: 0 };
  return {
    _calls: calls,
    put: async (r) => {
      calls.put.push(r);
    },
    readFallback: () => fallback,
    writeFallback: (records) => {
      calls.writeFallback.push(records);
      fallback = records;
    },
    sleep: async () => {
      calls.sleep++;
    },
    ...overrides,
  };
}

test("初回で成功すれば saved を返す", async () => {
  const deps = makeDeps();
  const result = await saveWithRetryAndFallback(makeRecord(), deps);
  assert.equal(result, "saved");
  assert.equal(deps._calls.put.length, 1);
});

test("1文字だけの入力でも保存される", async () => {
  const deps = makeDeps();
  const result = await saveWithRetryAndFallback(makeRecord({ rawText: "あ" }), deps);
  assert.equal(result, "saved");
  assert.equal(deps._calls.put[0].rawText, "あ");
});

test("感情だけの短文・絵文字も保存される", async () => {
  const deps = makeDeps();
  for (const text of ["疲れた", "もう無理", "うーん", "😢"]) {
    const result = await saveWithRetryAndFallback(makeRecord({ clientId: `id-${text}`, rawText: text }), deps);
    assert.equal(result, "saved");
  }
});

test("1・2回目が失敗し3回目で成功すれば saved、原文は変わらない", async () => {
  let calls = 0;
  const deps = makeDeps({
    put: async () => {
      calls++;
      if (calls < 3) throw new Error("一時的な書き込み失敗");
    },
  });
  const record = makeRecord({ rawText: "3回目で成功するはず" });
  const result = await saveWithRetryAndFallback(record, deps);
  assert.equal(result, "saved");
  assert.equal(calls, 3);
  assert.equal(record.rawText, "3回目で成功するはず");
});

test("IndexedDB相当が常に失敗しても緊急退避に保存されれば saved_via_fallback", async () => {
  const deps = makeDeps({
    put: async () => {
      throw new Error("IndexedDBが常に使えない");
    },
  });
  const record = makeRecord({ rawText: "死んでいても失われないはず" });
  const result = await saveWithRetryAndFallback(record, deps);
  assert.equal(result, "saved_via_fallback");
  const written = deps._calls.writeFallback.at(-1);
  assert.ok(written.some((r) => r.rawText === "死んでいても失われないはず"));
});

test("IndexedDBも緊急退避も両方失敗した場合のみ failed", async () => {
  const deps = makeDeps({
    put: async () => {
      throw new Error("失敗");
    },
    writeFallback: () => {
      throw new Error("localStorageも失敗");
    },
  });
  const result = await saveWithRetryAndFallback(makeRecord(), deps);
  assert.equal(result, "failed");
});

test("緊急退避で同一clientIdは重複せず新しい内容に収束する", async () => {
  let fallback = [makeRecord({ clientId: "dup-id", rawText: "古い内容" })];
  const deps = makeDeps({
    put: async () => {
      throw new Error("常に失敗");
    },
    readFallback: () => fallback,
    writeFallback: (records) => {
      fallback = records;
    },
  });
  await saveWithRetryAndFallback(makeRecord({ clientId: "dup-id", rawText: "新しい内容" }), deps);
  assert.equal(fallback.length, 1);
  assert.equal(fallback[0].rawText, "新しい内容");
});

test("recoverWithRetry: 退避先が空なら0", async () => {
  const deps = makeDeps();
  const recovered = await recoverWithRetry(deps);
  assert.equal(recovered, 0);
});

test("recoverWithRetry: 復旧できたレコードは退避先から消える", async () => {
  let fallback = [makeRecord({ clientId: "a", rawText: "退避A" }), makeRecord({ clientId: "b", rawText: "退避B" })];
  const deps = {
    put: async () => {},
    readFallback: () => fallback,
    writeFallback: (records) => {
      fallback = records;
    },
  };
  const recovered = await recoverWithRetry(deps);
  assert.equal(recovered, 2);
  assert.equal(fallback.length, 0);
});

test("recoverWithRetry: 一部失敗しても成功分だけ取り除かれる", async () => {
  let fallback = [makeRecord({ clientId: "ok", rawText: "成功" }), makeRecord({ clientId: "ng", rawText: "失敗" })];
  const deps = {
    put: async (r) => {
      if (r.clientId === "ng") throw new Error("まだ失敗");
    },
    readFallback: () => fallback,
    writeFallback: (records) => {
      fallback = records;
    },
  };
  const recovered = await recoverWithRetry(deps);
  assert.equal(recovered, 1);
  assert.equal(fallback.length, 1);
  assert.equal(fallback[0].clientId, "ng");
});
