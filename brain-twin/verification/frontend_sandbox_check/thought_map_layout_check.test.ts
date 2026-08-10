import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_SIM_CONFIG,
  initializeSimNodes,
  isSettled,
  radiusForThoughtCount,
  stepSimulation,
} from "../../apps/web/src/utils/thoughtMapLayout.ts";

// README.md参照: 公式テストスイート(apps/web/tests/, Vitest)ではなく、
// このサンドボックスで実際に力学シミュレーションを実行して検証する補助テスト。

function makeApiNode(overrides = {}) {
  return {
    id: "n1",
    label: "疲労",
    entityType: "topic",
    thoughtCount: 5,
    dominantSentiment: "negative",
    sentimentBreakdown: { negative: 5 },
    latestThoughtAt: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function distance(a, b) {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

test("radiusForThoughtCount: thoughtCountが多いほど半径が大きい", () => {
  assert.ok(radiusForThoughtCount(20) > radiusForThoughtCount(5));
  assert.ok(radiusForThoughtCount(5) > radiusForThoughtCount(1));
  assert.ok(radiusForThoughtCount(0) > 0);
});

test("initializeSimNodes: 同じseedなら再現性がある", () => {
  const nodes = [makeApiNode({ id: "a" }), makeApiNode({ id: "b" })];
  const sim1 = initializeSimNodes(nodes, DEFAULT_SIM_CONFIG, 42);
  const sim2 = initializeSimNodes(nodes, DEFAULT_SIM_CONFIG, 42);
  assert.deepEqual(sim1, sim2);
});

test("stepSimulation: 完全に重なった2ノードは反発して離れる", () => {
  let sim = [
    { id: "a", x: 400, y: 400, vx: 0, vy: 0, radius: 30 },
    { id: "b", x: 400, y: 400, vx: 0, vy: 0, radius: 30 },
  ];
  for (let i = 0; i < 30; i++) {
    sim = stepSimulation(sim, [], DEFAULT_SIM_CONFIG);
  }
  assert.ok(distance(sim[0], sim[1]) > 10, `距離: ${distance(sim[0], sim[1])}`);
});

test("stepSimulation: エッジで結ばれた遠いノードは近づく", () => {
  let sim = [
    { id: "a", x: 100, y: 400, vx: 0, vy: 0, radius: 30 },
    { id: "b", x: 700, y: 400, vx: 0, vy: 0, radius: 30 },
  ];
  const edges = [{ source: "a", target: "b", weight: 3 }];
  const initialDist = distance(sim[0], sim[1]);
  for (let i = 0; i < 30; i++) {
    sim = stepSimulation(sim, edges, DEFAULT_SIM_CONFIG);
  }
  assert.ok(distance(sim[0], sim[1]) < initialDist);
});

test("stepSimulation: エッジの重みが大きいほど強く引き寄せられる", () => {
  const makeSim = () => [
    { id: "a", x: 100, y: 400, vx: 0, vy: 0, radius: 30 },
    { id: "b", x: 700, y: 400, vx: 0, vy: 0, radius: 30 },
  ];
  let weak = makeSim();
  let strong = makeSim();
  for (let i = 0; i < 15; i++) {
    weak = stepSimulation(weak, [{ source: "a", target: "b", weight: 1 }], DEFAULT_SIM_CONFIG);
    strong = stepSimulation(strong, [{ source: "a", target: "b", weight: 10 }], DEFAULT_SIM_CONFIG);
  }
  assert.ok(distance(strong[0], strong[1]) < distance(weak[0], weak[1]));
});

test("stepSimulation: ノードは画面範囲外へ出ない", () => {
  let sim = [
    { id: "a", x: 10, y: 10, vx: 0, vy: 0, radius: 30 },
    { id: "b", x: 15, y: 15, vx: 0, vy: 0, radius: 30 },
  ];
  for (let i = 0; i < 50; i++) {
    sim = stepSimulation(sim, [], DEFAULT_SIM_CONFIG);
    for (const n of sim) {
      assert.ok(n.x >= 0 && n.x <= DEFAULT_SIM_CONFIG.width);
      assert.ok(n.y >= 0 && n.y <= DEFAULT_SIM_CONFIG.height);
    }
  }
});

test("stepSimulation: 8ノード+エッジでも発散しない(NaN/Infinityにならない)", () => {
  let sim = initializeSimNodes(
    Array.from({ length: 8 }, (_, i) => makeApiNode({ id: `n${i}`, thoughtCount: i + 1 })),
    DEFAULT_SIM_CONFIG,
    7
  );
  const edges = [
    { source: "n0", target: "n1", weight: 2 },
    { source: "n1", target: "n2", weight: 1 },
    { source: "n0", target: "n2", weight: 3 },
  ];
  for (let i = 0; i < 100; i++) {
    sim = stepSimulation(sim, edges, DEFAULT_SIM_CONFIG);
  }
  for (const n of sim) {
    assert.ok(Number.isFinite(n.x));
    assert.ok(Number.isFinite(n.y));
  }
});

test("isSettled: 単純な配置は十分なステップ後に安定する", () => {
  let sim = [{ id: "a", x: 400, y: 400, vx: 0, vy: 0, radius: 30 }];
  for (let i = 0; i < 20; i++) {
    sim = stepSimulation(sim, [], DEFAULT_SIM_CONFIG);
  }
  assert.equal(isSettled(sim), true);
});

test("isSettled: 速度が残っていればfalse", () => {
  const sim = [{ id: "a", x: 400, y: 400, vx: 5, vy: 5, radius: 30 }];
  assert.equal(isSettled(sim), false);
});
