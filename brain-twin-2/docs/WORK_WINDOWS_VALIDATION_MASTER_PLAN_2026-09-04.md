# Brain Twin — Windows実機・不足検証 Master Plan

Date: 2026-09-04

Status: **execution plan / evidence contract; execution routing PAUSED pending PA1 focused-repair independent Critical=0/Major=0 re-review**. Focused-repair commit `f9cb9652afc3f4b1838074091fbad3e510821c76` has exact-SHA green CI (run `33798627068`, 571 passed). This document does not claim that Windows model execution has already happened.

The stages below remain the intended order after that gate clears. They are not current authorization to
run the full Retrieval/Organizer matrix or select/freeze a model. `docs/CURRENT_STATE.md` is the live routing source.

## 1. 目的

Brain Twin のモデル選定を「動いた」「ベンチが良かった」で終わらせず、次を分離して証明する。

1. **実行可能性** — 対象 Windows PC でモデルが実際にロード・推論できる。
2. **品質** — 日本語の曖昧な記憶検索 / 雑な入力整理で必要な品質が出る。
3. **再現性** — 同じ Git / model revision / prompt / schema / runtime で結果が再現する。
4. **資源適合性** — CPU / RAM / disk / latency が常用可能な範囲に収まる。
5. **証拠完全性** — 比較条件が混ざっておらず、後から設定を差し替えられない。
6. **安全性** — Raw Log / Vault SOT を壊さず、remote code や外部通信を暗黙に許可しない。

## 2. 現時点で証明済みのこと

### Retrieval

- Phase 4 Vector Retrieval Core は CI 上 COMPLETE。
- PA1 open benchmark / formal-blind tooling / challenger catalog / Qwen matrix / challenger matrix は実装済み。
- Qwen / BGE-M3 / multilingual E5 / MiniLM の標準比較経路は準備済み。
- Nomic / GTE は custom-code revision まで pin 済みだが、通常評価へは fail-closed。

### Organizer

- 240件の privacy-safe synthetic open-v3 corpus がある（open-v2 192件 + stress 48件）。
- strict JSON / memory-worthy / type / topic / entity / date / importance / link / calibration を評価できる。
- Formal Blind は model-side package と private scoring を分離済み。
- Qwen3.5 0.8B / 2B / 4B、Qwen3-4B-Instruct-2507 を immutable revision で catalog 化済み。
- Windows evaluation venv / frozen package preflight / 0.8B first smoke が準備済み。

## 3. まだ証明できていないこと

以下は **Linux CI が成功していても代替できない**。

### A. Windows実モデル evidence

- Qwen embedding / reranker の対象 Windows CPU 実行。
- BGE / E5 / MiniLM の同一 PC 比較。
- Nomic / GTE custom-code smoke。
- Organizer Qwen3.5 0.8B / 2B の実ロード・推論。
- 実 RAM / load time / warm latency / disk footprint。

### B. 実用負荷

open-v3は次の入力形状をsynthetic stress sliceとして追加済みだが、Windows実行証拠・実データ代表性・
長時間負荷をまだ証明していない。

- 長い雑記・話題が途中で飛ぶ入力。
- 改行、箇条書き、URL、JSON、コード断片、絵文字を含む入力。
- 日本語 + 英語 + カタカナの混在。
- 誤字、略語、主語省略。
- 「前の指示を無視して～」のような prompt-injection 文字列を Raw Capture に含むケース。
- 2つ以上の予定 / 決定 / 否定が同居するケース。
- 長時間連続処理後の thermal / memory drift。

これらはFormal Blindとは分離したopen-development診断であり、追加済みという事実だけでは
モデル品質・実用性・本番採用を証明しない。

### C. Runtime代表性

Organizer の最初の基準実装は Transformers CPU / quantization=none。これは **参照品質を測る経路**であり、最終的な常用 runtime が決まったことを意味しない。

0.8B / 2B の品質が十分でも速度・RAMが悪ければ、同じ frozen model/prompt/schema を使って量子化 runtime を別 identity として比較する必要がある。逆に reference runtime が遅いだけでモデル品質を否定してはいけない。

## 4. 実行順序

### Stage実行前の外部レビューgate

Retrieval評価のFormal Blind誤ready化とranking drift選定経路に対するfocused repairは
exact-SHA CI成功済み。独立レビューCritical=0/Major=0になるまでは、以下を実行しても
**診断以外には使えない**。現時点では新規matrix実行自体を停止し、review handoffを優先する。

### Stage 0 — Windows Evidence Preconditions

必須:

- `brain-twin-dev`
- tracked worktree clean
- `git pull --ff-only`
- exact 40-char Git SHA 記録
- OS / Python / CPU / logical cores / RAM 記録
- production Vault を評価入力にしない

失敗したらその場で STOP。バージョンや prompt を勝手に変えて続行しない。

### Stage 1 — Retrieval full open matrix

**現在PAUSED**。独立レビューgate通過後にのみ再開する。

```powershell
git switch brain-twin-dev
git pull --ff-only origin brain-twin-dev
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\brain-twin-2\scripts\run_pa1_full_open_matrix.ps1
```

確認するもの:

- Qwen instruction EN / JA / none
- Qwen dimension 1024 / 768 / 512 / 256
- reranker OFF / ON
- BGE-M3
- multilingual-e5-base
- multilingual-e5-large-instruct
- MiniLM control
- exact Git / dataset identity
- latency / RSS / disk

**open winner = production winner ではない。**

### Stage 2 — Retrieval custom-code candidates

Nomic / GTE は通常 matrix へ直接入れない。

1. exact model revision を確認
2. exact custom-code revision を確認
3. offline smoke
4. dimension / normalization / local-only を確認
5. review 後にのみ比較候補へ昇格

### Stage 3 — Organizer Windows bootstrap

From `brain-twin-2`:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_organizer_eval_windows.ps1
```

setup が成功してもモデル品質の証拠ではない。

### Stage 4 — Organizer 0.8B first smoke

```powershell
.\scripts\smoke_organizer_qwen08_windows.ps1
```

ここでは 0.8B だけ取得する。

確認:

- exact HF model revision
- local artifact full SHA-256 tree
- loader成功
- strict JSON
- deterministic repeat
- artifact verification time
- model load time
- generation latency
- RSS
- disk

loader/schema/artifact/runtime error がある場合、2Bを先に落として問題を隠さない。

### Stage 5 — Organizer isolated core comparison

0.8B smoke が clean のときのみ:

```powershell
.\scripts\run_organizer_core_windows.ps1
```

0.8B と 2B は **別 Python process** で実行する。理由は Torch allocation / process PeakWorkingSetSize / allocator history が次モデルへ混ざると RAM 比較が壊れるため。

比較軸:

- schema_valid_rate
- strict_record_accuracy
- memory_worthy_f1
- memory_type_accuracy
- topics_f1
- entities_f1
- entity_hallucination_rate
- event_date exact / null accuracy
- importance error
- links_f1
- confidence calibration
- deterministic repeat
- model artifact identity
- model load time
- inference latency
- RSS
- disk

### Stage 6 — Extended Organizer only if justified

2B が品質不足、または 4B 増分が合理的に見込める場合だけ:

- Qwen3.5-4B
- Qwen3-4B-Instruct-2507

を追加する。

「大きい方が良さそう」だけでは取得しない。2Bとの差を quality gain / resource cost の両方で説明する。

### Stage 7 — Stress / robustness corpus

Formal Blind 前に open-development stress set を追加する。

最低限必要な slices:

1. prompt_injection_as_data
2. long_capture
3. multiline_markdown
4. embedded_json_or_code
5. jp_en_mixed
6. typo_abbreviation
7. emoji_punctuation
8. multi_intent
9. cancelled_then_replanned
10. ambiguous_pronoun
11. many_entities
12. no_memory_chatter

特に prompt injection は、Raw Capture 内の命令文を **データ**として扱い、system organizer contract を上書きしないことを確認する。

### Stage 8 — Repeatability / thermal drift

provisional winner は少なくとも別プロセスで複数回実行し、次を確認する。

- quality metric が同一または説明可能
- determinism mismatch = 0
- latency の極端な劣化がない
- RSS が run ごとに増え続けない
- 長時間連続実行で crash / swap pressure が出ない

1回だけ速かった結果を採用根拠にしない。

### Stage 9 — Freeze before Formal Blind

open evidence を見た後、**blindを見る前**に次を固定する。

- model revision
- prompt SHA
- output schema SHA
- chat template/tokenizer SHA
- runtime/version
- quantization
- generation params
- model artifact identity
- Windows latency/RAM/disk budgets
- quality thresholds
- critical slice rules
- evaluator Git SHA

その後にだけ Formal Blind を1回実行する。

## 5. 非交渉 Evidence Gates

品質閾値の数字とは別に、以下は現時点から固定してよい。

- tracked Git dirty → **FAIL / rerun**
- model revision mismatch → **FAIL**
- local artifact SHA mismatch → **FAIL**
- unexpected remote-code → **FAIL**
- formal runでnetwork dependency → **FAIL**
- candidate間でdataset SHAが違う → **FAIL**
- candidate間でevaluator Git SHAが違う → **FAIL**
- deterministic greedy設定で結果drift → **FAIL candidate until explained**
- production Vaultへ評価ツールが書き込む → **STOP**
- open benchmarkだけでproduction採用を宣言 → **STOP**

品質/RAM/latencyの具体値は open evidence を得てから policy に固定し、その後 blind の結果を見て変更しない。

## 6. 疑うべきポイント

| 仮説 | 反証方法 |
|---|---|
| Qwenが一番良いはず | BGE/E5/controlを同一dataset/Gitで比較 |
| 2Bなら0.8Bより必ず良い | strict/hallucination/resourceの実測差を見る |
| schema validなら整理品質も良い | strict/type/entity/date/linkを別々に確認 |
| entity F1が高ければ安全 | hallucination rateを独立gateにする |
| CPUベンチ1回で十分 | fresh process repeat + thermal drift確認 |
| model revisionが同じなら同一artifact | local tree SHA-256で破損/改変を検出 |
| 大きいモデルほど実用的 | latency/RAM/disk増分をquality gainで正当化 |
| Transformers referenceが遅ければモデルが不採用 | qualityとruntime implementationを分離して判断 |
| syntheticで良ければ実入力でも良い | stress + genuine held-outを別に要求 |
| prompt injectionは自分のメモなので無関係 | pasted contentに命令が入るケースを明示試験 |

## 7. 「証拠」と呼ばないもの

- model card のベンチマークだけ
- Linux CIだけ
- loaderが起動しただけ
- 8件 smoke の品質だけ
- open corpus の winner だけ
- 1回のlatency値だけ
- Git SHAなしのスクリーンショット
- model revisionだけでlocal file integrity未確認のrun

## 8. 最終判定の順番

```text
Windows実行可能
  ↓
Open quality / resources
  ↓
Stress / repeatability
  ↓
Provisional model + runtime
  ↓
Policy / budget freeze
  ↓
Private held-out + adjudication
  ↓
One sealed Formal Blind
  ↓
Independent evidence review
  ↓
PA1 / Organizer model selection GO
  ↓
PA2 / PA3 / production integration
```

Production activation を、この順序より前へ移動しない。
