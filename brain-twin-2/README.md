# Brain Twin 2.0 — Phase 1–3: Memory Foundation, Automatic Memory Worker & Retrieval

> スマホでは思ったことを呟くだけ。PC側で自動整理し、Obsidianに長期記憶として保存し、
> 必要なときにAIが検索・連想・比較して思い出せる第二の脳。

Brain Twinの本体はAIそのものではなく、**永続的な記憶基盤**です。AIモデルは将来交換可能にします。
このディレクトリは「Claude Code向け実装指示書」の **Phase 1(Memory Foundation)** と
**Phase 2(Automatic Memory Worker のうち Entity Extraction / Link生成)** を実装したものです。

- LLM APIは使いません(Phase 1・2はダミー分類/ルールベースで十分という指示書の方針通り)。
- Dockerは不要です。Python + Markdown + SQLite + Obsidian のみで動きます。
- **Markdown(Obsidian Vault)が正本、SQLiteは検索用のindex/cache**です。SQLiteが壊れても
  `python brain.py reindex` でVaultから作り直せます(Phase 2で追加したentity/linkの
  情報も含めて完全に復元できることを確認済み)。

---

## セットアップ

### Windows (PowerShell)

```powershell
cd brain-twin-2
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup.ps1
```

### 手動 (macOS/Linux/Windows共通)

```bash
cd brain-twin-2
python3 -m venv .venv
source .venv/bin/activate   # Windowsは .venv\Scripts\activate
pip install -r requirements.txt
pytest tests/ -q
```

`brain-twin-2/` 配下の変更をpush/PRすると、`.github/workflows/brain-twin-2-tests.yml` が
自動的に `pytest tests/` を実行する(最小限のCI。他プロジェクト(`brain-twin/`)や
本体の設計には影響しない)。

## 使い方

```bash
python brain.py add "今日はBrain Twinの設計について考えた"
python brain.py process
python brain.py search "Brain Twin"
```

### Phase 3 Retrieval

通常の `search` は従来どおり、FTS5 と importance / confidence / recency による
Primary Memory のみを返します。`--related` を付けると、各 Primary から保存済みLinkを
1-hopだけ辿り、関連Memoryを別枠で表示します。Phase 2のLinkは一方向保存ですが、検索時は
outgoing / incoming の両方向を探索します。

Link生成時にPhase 2が計算した `strength` は、Memory frontmatterの `link_details` と
SQLite `links.strength` の双方へ保存され、Retrievalはrelation_type固定優先度ではなく
この実値を使います。同じRelated Memoryへの複数relationは、Link生成時と同じくstrengthの
合計で集約し、Primary順位・importanceを決定的なtie-breakerにします。strength導入前の
legacy `link_details` は生成時の実値を復元できず、旧Entity抽出の誤検出を強く扱わないため、
relation_typeを問わず保守的な `0.25` として復元します。

候補ranking時はMemory本文を取得せず、memory_id・relation・strength・importanceなどの
軽量signalだけを扱います。`related_limit` 件を選抜した後、そのIDの表示詳細だけをSQLiteから
取得するため、大量のincoming Linkがあっても全候補本文をPythonへロードしません。

```bash
python brain.py search "Brain Twin"
python brain.py search "Brain Twin" --related
python brain.py search "Brain Twin" --related --related-limit 20
```

Timeline Search はLong-term Memoryの `event_date` を基準に、activeなMemoryを日付昇順で
一覧します。境界日は含まれ、`--from` または `--to` の片方だけでも指定できます。
日付を省略するとactiveなMemoryを全期間から一覧します。

```bash
python brain.py timeline --from 2026-08-01 --to 2026-08-31
python brain.py timeline --from 2026-08-01
python brain.py timeline --to 2026-08-31
python brain.py timeline
```

- `add` — 思ったことをそのまま記録するだけ。整理はしない(指示書2章「ユーザーに整理させない」)。
- `process` — 未処理の入力をDaily Logへ保存し、Long-term Memoryに昇格させるかをPhase 1のダミー
  分類器(`brain_twin/classify.py`、キーワードベース)で判定する。雑談は消さずDaily Logに残す。
  昇格させた場合、Phase 2のEntity抽出(`brain_twin/entity_extract.py`)とLink生成
  (`brain_twin/linking.py`)も同時に行う。
- `search` — Long-term Memoryをキーワード検索する(FTS5 + importance/confidence/recencyの
  簡易Hybrid Retrieval)。抽出済みのentitiesも結果に表示される。
- `reindex` — SQLite indexが壊れた/消えた場合に、Vault(Markdown)から作り直す
  (entities/linksも含めて完全に再構築される)。

Vaultは既定で `brain-twin-2/vault/` に作成されます。**Obsidianでこのフォルダを開くと**、
Daily Log・Memory・メタデータ(frontmatter)を人間が普通に閲覧できます。

### Sprint 4C/4D: Vector / Hybrid Primary Search(外部レビュー待ち)

`search` に `--vector` / `--hybrid` を付けると、通常のFTS5 lexical検索の代わりに
Vector Primary SearchまたはHybrid Primary Search(lexical + vectorのWeighted
Reciprocal Rank Fusion)を使う。両者は互いに排他(argparseレベルで拒否)。
`--related`(Sprint 3のAssociative Retrieval)は Sprint 4D で `--vector`/`--hybrid`
と併用できるようになった(`retrieval.retrieve_from_primary()`が共通の1-hop展開を担う)。

```bash
python brain.py search "Brain Twin" --vector
python brain.py search "Brain Twin" --hybrid
python brain.py search "Brain Twin" --hybrid --verbose  # fusion/metadata_multiplier等の内訳も表示
python brain.py search "Brain Twin" --hybrid --related  # Hybrid Primary + 1-hop関連Memory
```

Vector系検索は、user configで選んだembedding profileがSQLite上でactiveかつ、選択した
`VectorIndexBackend`のbuildがそのprofileに対して`ready`である場合にのみ動く
(`vector_search.check_vector_availability`)。条件を満たさない場合は黙ってlexical検索へ
fallbackせず、`[NG] Vector search: ...`という明確なエラーで拒否する。本番のembedding
providerとsqlite-vec backendはまだ実装していない(`ExactScanBackend` + fake providerのみ)ため、
標準配布のまま`--vector`/`--hybrid`を使うと「provider is not installed」系のエラーになる
(`python brain.py embeddings sync`と同じ制約)。詳細な設計は
`docs/VECTOR_SEARCH_DESIGN.md`の14節(Sprint分割案)を参照。

## プロジェクト構成

```
brain-twin-2/
├ brain.py              # CLIエントリポイント
├ brain_twin/
│  ├ config.py           # Vault/DBの場所
│  ├ models.py           # MemoryType等の型定義
│  ├ ids.py               # ID生成 (mem_20260814_001 形式)
│  ├ frontmatter.py       # YAML frontmatterの読み書き
│  ├ vault.py             # Obsidian Vaultのフォルダ構成を用意
│  ├ classify.py          # Phase 1のダミー分類器(キーワードベース)
│  ├ entity_extract.py    # Phase 2: Entity Extraction(カタカナヒューリスティック)
│  ├ linking.py           # Phase 2: Memory間のLink生成(同トピック/同エンティティ/時間的近さ)
│  ├ raw_log_io.py        # Layer 1(Raw Log) / Layer 2(Daily Log)
│  ├ memory_io.py         # Layer 3(Long-term Memory)
│  ├ db.py                # SQLite index (FTS5 trigram + entities/links)
│  ├ memory_persistence.py # MemoryをSQLiteへ反映する共通処理(pipeline/reconcileの両方が使う)
│  ├ reconcile.py         # processed_atの反映漏れ(commit前クラッシュ)を検出・自己修復
│  ├ pipeline.py          # add / process / reindex の実処理
│  ├ search.py            # 簡易Hybrid Retrieval(lexical、Phase 1〜3)
│  ├ retrieval.py         # Phase 3: Associative Retrieval(保存済みLinkの1-hop展開)
│  ├ retrieval_weights.py # metadata_multiplier等、lexical/HybridのRanking重みを1箇所に集約
│  ├ embedding_provider.py   # Embedding Provider Protocol・profile・typed errors(SDK非依存)
│  ├ embedding_config.py     # user config(Git管理外)の読み込み・secret値の拒否
│  ├ embedding_document.py   # canonical embedding document + content hash
│  ├ embedding_vector.py     # canonical float32 BLOB encode/decode
│  ├ embedding_repository.py # embedding cache用のSQLite repository層
│  ├ embedding_service.py    # 再構築可能なembedding cacheのsync/rebuild orchestration
│  ├ embedding_runtime.py    # user configからprovider/backendインスタンスを組み立てる
│  ├ vector_index.py      # VectorIndexBackend Protocol
│  ├ vector_exact.py      # ExactScanBackend(小規模/フォールバック用のBLOB全走査cosine検索)
│  ├ vector_search.py     # Sprint 4C: Vector Primary Search + availability gate
│  ├ hybrid_search.py     # Sprint 4C: Hybrid Primary Search(Weighted RRF)
│  └ cli.py               # argparseによるコマンド定義
├ tests/                  # pytest (298 tests)
├ scripts/setup.ps1
├ vault/                  # 実際のVault(Git管理外、実行時に自動生成)
└ data/                   # SQLite index(Git管理外)
```

### Vault構成 (指示書6章)

```
vault/
├ 00_Inbox/       # Raw Log (原文そのまま。改変禁止)
├ 10_Daily/       # Daily Log (1日1ファイル)
├ 20_Memory/      # Long-term Memory
│  ├ Experiences/ Thoughts/ Decisions/ Preferences/ Goals/ Facts/
├ 30_Projects/    # type: project のMemory (Phase 2以降で本格運用)
├ 40_Knowledge/   # type: knowledge
├ 50_People/      # type: person
├ 60_Goals/       # 目標の俯瞰ビュー (Phase 5)
├ 70_Timeline/    # 時系列の変化を追うビュー (Phase 5)
├ 80_AI/          # type: ai_inference (Phase 4以降)
└ 90_System/      # このツールが使う内部情報
```

## 設計上の判断(指示書38章に基づく記録)

- **`brain-twin/`(既存のFastAPI/Docker版)とは別ディレクトリにした**: 指示書はDocker不要・
  Python+Markdown+SQLite+Obsidianというまったく別の技術構成を前提にしており、既存の
  FastAPIバックエンドを土台にすると無関係な依存(Docker/SQLAlchemy/非同期API)を持ち込む
  ことになるため。ただし `brain-twin/` で検証済みだったFTS5(trigram) + トリガー同期という
  DBパターンは、そのまま `brain_twin/db.py` で再利用している。
- **PyYAMLを依存に追加した**: frontmatterの読み書きを自前の簡易パーサで済ませることもできたが、
  往復での破損(日本語・リスト・null等)のリスクを避けるため、実績のあるPyYAMLを採用した。
  「Dockerを必須にしない」という指示書の方針に反しない範囲の、軽量なpip依存1つのみ。
- **ID生成は2種類を使い分ける**(`brain_twin/ids.py`)。raw_logはVault上の既存ファイルを
  スキャンして連番を決める(指示書25章「SQLiteが壊れてもMarkdownから再構築可能にする」を
  ID生成の場面でも徹底するため)。Memoryは(2026-08-24のレビュー修正で)raw_log_idから
  決定的に導出する方式へ変更した。理由は後述の「レビュー修正」節を参照。
- **グローバルな接続オブジェクトを作らない設計にした**: 全関数が `Config` を明示的な引数として
  受け取り、DB接続もその都度 `db.connect(config)` で開く。これは指示書15章が警告している
  「app.db.engineがimport時に固定され、テスト用DBへの差し替えが効かない」という過去の回帰を
  構造的に起こらないようにするため(テストは `tests/conftest.py` で `tmp_path` ベースの
  `Config` を直接組み立てるだけで、本番Vault/DBに一切触れない)。
- **Phase 1の分類器はキーワードベースの完全なダミー**(`brain_twin/classify.py`)。
  「決めた/することにした」→decision、「好き/嫌い」→preference、「したい/やりたい」→goal、
  それ以外で12文字以上なら thought/experience、それ未満は雑談としてDaily Logのみに残す
  というごく粗いルール。confidenceは常に1.0(=本人の原文をそのまま保持しているだけで、
  AIによる推測は一切行っていないため。指示書11章)。Phase 4で実際のLLM分類に差し替える
  際も `ClassificationResult` という同じ形の値を返させれば済むようにしてある。
- **検索対象はLong-term Memoryのみ**とし、Daily Log(雑談を含む生ログ)は検索対象に
  含めていない。指示書15章のHybrid Retrievalの説明がMemoryを主語にしていることに合わせた。
- **`ask`(自然言語での質問応答)は未実装**。指示書28章でPhase 4「AI Brain」に
  明示的に分類されており、LLM接続が前提のため。今回のPhase 2の範囲にも含まれていない。

### Phase 2(Entity Extraction / Link生成)での判断

- **Entity抽出は「カタカナの連続2文字以上」というヒューリスティックのみ**
  (`brain_twin/entity_extract.py`)。指示書に登場する実例("ナイキ"「クラルティ」)がいずれも
  カタカナ表記であることから、Phase 1の分類器と同じ「重いNLP依存を追加しない」方針のまま
  実用的な価値を出せると判断した。MeCab/GiNZA等の形態素解析器の追加はモデル選定や
  Windowsでの動作確認まで含む大きな設計変更になるため、このPhaseでは行っていない
  (指示書24章の簡素な構成という方針、指示書38章「最小差分」を踏まえた判断)。
  既知の限界として、"カバン"のような一般名詞の外来語も一緒に拾ってしまう(誤検出はあるが
  見逃しより検出寄りに倒す設計。人名の漢字表記等は対象外)。
- **Link生成は `same_topic` / `same_entity` / `temporal_relation` の3種類のみ**
  (`brain_twin/linking.py`)。ベクトル類似度は使わない(Vector Searchは別Phase)。
  `brain-twin/apps/server/app/core/linking.py` で既に検証済みだった設計(依存フリーな
  純粋関数、strengthでソートして上位N件のみ採用)をそのまま踏襲した(指示書38章)。
- **リンクは新規Memoryから既存Memoryへの一方向のみ生成し、既存ファイルは書き換えない**。
  Obsidianはsourceにしか `[[wikilink]]` が無くてもLinked Mentions(backlink)パネルで
  双方向に表示するため、過去に書いたMemoryファイルへ触れる必要がない
  (指示書3-11相当の「原文を後から書き換えない」という考え方を、Memory確定後のファイルにも
  適用した)。
- **frontmatterの `links` は指示書7章の例と同じ `"[[mem_id]]"` 形式の文字列リストのまま
  維持しつつ、`link_details`(target/relation_type/reasonを持つ辞書のリスト)を新設した**。
  `links` だけでは関係の種類(同トピックか同エンティティか等)を保持できず、
  `reindex` でSQLiteの `links` テーブルを完全に復元できなくなるため
  (指示書25・34章「SQLiteはMarkdownから再構築可能」を壊さないための拡張)。
  `links` は同一targetをまとめて重複排除するが、`link_details` は関係の種類ごとに
  複数持てる(1つのMemoryペアが同時に「同エンティティ」かつ「時間的に近い」こともあるため)。
- **`entities` / `links` テーブルは正規化し、Memoryの `topics_json` のような
  JSON列にはしなかった**。Phase 1の時点で既にこの2テーブルがスキーマに用意されており
  (未使用のまま)、既存設計の意図を尊重してそのまま活用した。バッチ取得用の
  `db.entities_for_memories()` はN+1を避ける(`brain-twin/`の
  `load_thought_entities_batch` と同じ考え方)。
- **`reindex` はMemory挿入とLink挿入を2周に分けている**。1周目で全Memoryを`memories`
  テーブルへ挿入してから、2周目でlinksを挿入する。Vault内のファイル列挙順序と
  作成順序は一致しない(フォルダごとにグルーピングされるため)ため、1周で処理すると
  「まだ存在しないMemoryへのリンク」を外部キー制約が拒否してしまう。
  `test_links_table_rejects_dangling_reference` でこの制約自体を、
  `test_reindex_reproduces_links_and_entities_from_markdown` で2周構成が正しく
  機能することをそれぞれ確認している。
- **`links` テーブルへ `reason` 列を追加したことに伴い、既にPhase 1のスキーマで
  DBを作成済みの環境でも壊れないよう `db.connect()` に自己修復(`ALTER TABLE ADD COLUMN`)
  を追加した**。「データ消失につながる変更は禁止」という原則を踏まえ、`reindex`を
  必須にせず、CREATE TABLE IF NOT EXISTSでは新しい列が追加されないというSQLiteの制約を
  補う最小限の対応とした(`test_connect_self_heals_pre_phase2_links_table_missing_reason_column`
  で検証済み)。

## レビュー修正(2026-08-24)

Phase 2実装(コミット `6342152`)に対するレビューで5件の問題が指摘され、以下のように対応した。
既存の設計・アーキテクチャ(責務分離: db層/linking層/entity_extract層/memory_io層)は
変更していない。

1. **Entity誤検出が強いリンク根拠になっていた問題**: `entity_extract.py` が返す型を
   `list[str]` から `list[ExtractedEntity]`(name/confidence/method)へ変更し、
   `linking.py` の `same_entity` strengthを「両側confidenceの最小値」で重み付けするように
   変更した。confidenceの算出はSTOPWORDSの無限拡張ではなく、カタカナの長さに基づく
   基礎値(短いほど低い)+小さな補助リストによる軽い減点、という組み合わせにした。
   これに伴い `memory_entities` テーブルへ `confidence`/`method` 列を追加し、
   (Phase 2時点のスキーマからの追従のため)`db.connect()` の自己修復対象に加えた。
2. **MAX_LINKS_PER_MEMORYの意味の誤り**: `linking._select_top_memories()` で、
   「target_memory_idごとの合計strengthで上位10件のMemoryを選び、選ばれたMemoryに
   付随する全relationをそのまま返す」方式に変更した(以前はrelation行単位で10件に
   切っていたため、1ペアに複数種類の関連が発生すると実質3〜4件しか残らなかった)。
   「10 relatedMemory」を意図した設計だったと判断し、そのように修正した
   (判断理由は `linking.py` のモジュールdocstringにも記録)。
3. **直近500件への打ち切り**: `db.list_active_memory_signals`(全件Python走査)を廃止し、
   `db.find_candidates_by_topics` / `find_candidates_by_entities` /
   `find_candidates_by_time_range` の3つに分割した。それぞれSQLite側で絞り込み
   (`json_each`によるtopics_jsonの展開、entities/memory_entitiesのJOIN、
   created_atのBETWEEN)を行い、和集合を候補とする。件数ベースの打ち切りをやめたため、
   何年前のMemoryであっても、トピック・エンティティ・時間のいずれかが一致すれば
   候補になれる。スコアリング・順位付け(どれだけ強い関連か)は引き続き `linking.py`
   (Python側)の責務のままにしてあり、DB層は「関連しうる候補の絞り込み」だけを担当する。
4. **reindex時にlink.created_atが失われる問題**: `link_details` の各要素へ
   `created_at`(そのリンクが生成された時刻)を追加し、`reindex`・process再実行時の
   どちらもこの値を使ってSQLiteへ書き戻すようにした(`pipeline._persist_links`に
   集約)。この修正より前に書かれたMemory(`link_details`に`created_at`を持たない)は
   `Memory.created_at`(Memory自体の作成時刻)にフォールバックする
   (`test_reindex_falls_back_to_memory_created_at_for_link_details_without_created_at`
   で検証)。
5. **process途中失敗時の二重Memory生成(最優先)**: Memory IDの採番方式を、
   Vaultスキャンによる連番(`ids.new_id`)から、raw_log_idからの決定的な導出
   (`ids.derive_memory_id`: `raw_20260824_003` → `mem_20260824_003`)へ変更した。
   これにより、同じraw_logに対するprocessが何度再試行されても、常に同じMemory IDを
   指す。`pipeline._process_one` は書き込み前に `memory_io.find_existing()` で
   既存ファイルの有無を確認し、存在すればそれを正として再利用する(entities/linksの
   再計算はしない。再計算すると、クラッシュ前後で他のMemoryの状況が変わっている
   可能性があり、結果が変わって一貫性が崩れうるため)。あわせて、Memory Markdownの
   書き込み自体も一時ファイル+rename方式で原子的にした(`vault.write_text_atomic`)。
   これは今回のテストシナリオ自体が要求するものではないが、
   「書き込み済みファイルを正として再利用する」という仕組み全体が、書き込み途中の
   破損ファイルに対しては機能しないため、その前提を守るために追加した
   (この判断もこの節で明記しておく)。

## レビュー修正(2回目, 2026-08-24)

1回目のレビュー修正(コミット `4e5f3fd`)に対する2回目のレビューで、さらに5件の問題が
指摘され、以下のように対応した。既存の設計・アーキテクチャ(責務分離)はここでも維持し、
新たに追加したのは「MemoryをSQLiteへ反映する処理」を独立させた `memory_persistence.py`
と、reconcile専用の `reconcile.py` の2モジュールのみ。

1. **候補探索の「200件制限」の解消**: 1回目の修正で「直近500件」の全件Python走査は
   撤廃したが、`find_candidates_by_topics` / `find_candidates_by_entities` /
   `find_candidates_by_time_range` の各SQLクエリには `ORDER BY created_at DESC LIMIT 200`
   が残っており、"一致する集合の中で新しい200件だけ"という形で同じ問題(古いMemoryが
   候補から漏れる)が再発していた。この`LIMIT`を撤廃し、一致するIDを全件返すように
   した。件数が増えたときの安全性は、打ち切りではなく**バッチ処理**で確保する:
   `entities_for_memories` / `list_memory_signals_by_ids` は候補IDが多い場合でも
   SQLiteの `IN (?, ?, ...)` プレースホルダ上限(`SQLITE_MAX_VARIABLE_NUMBER`)に
   引っかからないよう、500件単位(`db._chunked`)に分割して問い合わせる。スコアリング・
   上位N件への絞り込みは引き続き `linking.py` の責務のまま。201件が同じtopic/entityを
   共有する状況で最も古い1件が候補に含まれることを、`test_db_entities_links.py` に
   追加したテストで確認している(「古いMemoryが1件だけ」という設定では打ち切りの
   有無を区別できないため、201件という具体的な件数で検証している)。
2. **Raw Log / Daily Logの書き込みが非atomicだった問題**: `raw_log_io.write_raw_log` /
   `mark_processed` / `append_to_daily_log` を、Memory Markdownと同じ
   `vault.write_text_atomic()` 経由に変更した。Raw LogはVault内で最も失ってはいけない
   原本(整理される前の入力そのもの)であり、Memoryと同等以上に書き込み途中のクラッシュに
   強くあるべき、という指摘に基づく。`write_text_atomic` 自体もこの機会に補強した:
   一時ファイル名にPIDを含めて複数プロセスからの同時書き込みでも衝突しないようにし、
   書き込み中に例外が起きた場合は一時ファイルを削除してから再送出するようにした
   (`*.tmp` の残骸がVaultに残り続けない)。Windowsでの安全性(同一ファイルシステム内の
   `Path.replace()` が上書きを含めて原子的であること)は `vault.write_text_atomic` の
   docstringに根拠を記録した。`test_vault.py` を新設して検証している。
3. **processed_atがMarkdownには書けたがSQLite commitされない窓(最優先)**:
   `process_all()` は1件のraw_logについて (a) Memory Markdown書き込み → (b) Raw Log
   processed_at書き込み(Markdown) → (c) SQLiteへの反映+`conn.commit()` の順で処理する。
   (b)の直後・(c)のcommit前でクラッシュすると、Markdown上は「処理済み」なのにSQLiteには
   何も反映されない状態が残る。この状態のraw_logはMarkdownが「処理済み」と言っている以上
   `unprocessed_only=True` では二度と拾われず、`reindex` を手動実行するまで不整合が
   残り続けてしまう。これを解消するため `reconcile.py`(新設)に
   `reconcile_processed_raw_logs()` を実装した: 全raw_logのうちMarkdown上processed_at
   済みなのにSQLite側`raw_logs`が未反映(行が無い、またはprocessed_at NULL)のものを検出し、
   分類を再実行(`classify.classify`は純粋関数なので副作用なく再実行できる)して
   `memory_io.find_existing()`(後述の修正で全Vault検索になったもの)で既存Memoryを
   見つけ、`memory_persistence.persist_memory/persist_links` でSQLiteへ反映し直す。
   Memory Markdownが万一(手動編集等で)見つからない異常な場合は `ReconcileError` を
   送出し、黙って何もしない/でっち上げることはしない。この関数は `process_all()` の
   冒頭、DB接続を開いた直後・「未処理raw logが0件だから何もしない」という早期return
   より前に必ず呼ぶよう `process_all()` を再構成した(不整合のあるraw_log自体は
   Markdown上「処理済み」なので、そのままだと"unprocessed"が0件に見えてreconcile自体が
   スキップされてしまうため)。`pipeline.py`から独立したモジュールにしたのは、
   「1件のraw_logをSQLiteへ反映する」処理自体は`pipeline.py`の通常経路(`_process_one`)
   と`reconcile.py`の両方が必要とするため、`memory_persistence.py`へ切り出して
   両方から利用する形にし、`pipeline.py → reconcile.py → memory_persistence.py`という
   一方向の依存だけで済むようにした(`reconcile.py → pipeline.py`という循環は作らない)。
   12ステップの障害注入テスト(`test_process_all_auto_reconciles_raw_log_processed_in_markdown_but_never_committed_to_sqlite`、
   `test_pipeline.py`)で、クラッシュ直後の不整合発生と、次回`process_all()`実行時の
   自動修復(Memoryが重複しない・SQLiteとMarkdownの内容が一致する)の両方を確認して
   いる。`sqlite3.Connection`はイミュータブルな拡張型でメソッドを直接monkeypatchできない
   ため、`db.connect()`が返す接続を薄いプロキシ(`commit()`だけ差し替え、他は実接続へ
   委譲)に差し替える形で「mark_processed成功直後の最初のcommit()だけ失敗させる」を
   再現した。`test_reconcile.py` では `reconcile_processed_raw_logs()` 単体の
   振る舞い(不整合なしなら何もしない・SQLite側の行欠落を直せる・Memoryが見つからない
   異常系でReconcileErrorを送出する)も個別に検証している。
4. **Memory IDの一意性がVault全体ではなく現在の分類typeのフォルダ内でしか保証されて
   いなかった問題**: `memory_io.find_existing()` は以前、分類結果が示す1つのtypeの
   フォルダしか見ていなかった。クラッシュと再試行の間に分類ロジック自体が変わっていた
   場合(例: 同じ入力が前回はTHOUGHT、今回はDECISIONに分類される)、旧typeのフォルダに
   ある既存ファイルを見失い、新typeのフォルダへ同じIDのMemoryを重複生成してしまう
   可能性があった。`find_existing()` を、Vault全体(ただし`MEMORY_TYPE_FOLDER`にある
   有限個・現在10種類のtypeフォルダに限定)からIDを探すように変更した。`rglob`による
   Vault全体の再帰走査は使っていない: Memoryが置かれる場所はtype別フォルダに限られる
   というVaultの構成上の不変条件を利用し、候補パスをtypeの種類数(定数)に固定している
   ため、Vaultにraw log/daily log/添付ファイルがどれだけ増えても探索コストは変わらない。
   同じIDのファイルが複数のtypeフォルダに見つかった場合(本来あり得ない異常な状態)は、
   自動的にどちらかを選ばず `DuplicateMemoryError` を送出する。1回目の分類でTHOUGHTと
   判定されMemory書き込み直後にクラッシュし、2回目の分類(分類ロジックの変更を模擬)では
   DECISIONと判定される、というシナリオのテストを `test_pipeline.py` に追加し、
   Vault全体でMemoryが1件だけであること・元のMarkdown(THOUGHT)が正として再利用される
   こと・Decisionsフォルダに複製が作られないことを確認している。
5. **legacy Entityのconfidenceフォールバックが1.0(方向が逆)だった問題**:
   `memory_io.entity_objects()` は、`entity_details`を持たない旧形式のMemory
   (`entities: [...]`のみ)に対して`confidence=1.0`(最大の信頼度)を割り当てていたが、
   これは実態と逆である。`entity_details`が無いということは、そのデータはconfidenceに
   よる重み付けという概念が導入される前の抽出器が出したものであり、その版は
   「カタカナ連続2文字以上ならほぼ無条件にentityとみなす」というルールしか持たず、
   一般的な外来語("アプリ"「スマホ」等)も選別なく拾っていた(現行版にある
   `_GENERIC_HINTS`による減点や語長に基づく基礎confidenceの考え方が無い)。つまり
   legacyデータは現行のconfidence設計から見て精度が現行の最低ラインより低い側であり、
   1.0は逆方向の扱いになっていた。`_LEGACY_ENTITY_CONFIDENCE = 0.3` を新設して
   採用した。この値は、現行の`entity_extract.py`で既知の一般語リストに載っていない
   通常の語であっても最短カテゴリ(カタカナ2文字)に割り当てられる最も低い基礎confidence
   (`_base_confidence(2) == 0.3`)と同じ水準であり、「legacy抽出はどの語であれ、現行
   ヒューリスティックが付けうる最も慎重な評価と同程度にしか信頼しない」という保守的な
   扱いになっている(採用理由の詳細は`memory_io.entity_objects()`のdocstringに記録)。
   `test_memory_io.py` で、method="legacy"になること・confidenceが1.0でないこと・
   legacy由来の一般語1件の一致だけではsame_topicと同等のstrengthを持つ強いリンクの
   根拠にならないこと、をそれぞれ確認している。

### 追加で確認した項目

- **`vault.write_text_atomic()` のWindows安全性**: 一時ファイルは対象ファイルと同じ
  ディレクトリに作るため同一ファイルシステム上に置かれることが保証されており(異なる
  ボリューム間のrenameは原子的でない)、`Path.replace()`はWindows上でも既存ファイルへの
  上書きを含めて原子的に行える(`os.rename()`単体とは異なる)。一時ファイル名にPIDを
  含めることで複数プロセスの同時書き込みでも衝突しない。書き込み中の例外は一時ファイルを
  削除してから再送出するため`*.tmp`の残骸が残らない。
- **今回のSQLite変更の後方互換性**: 新規に追加したテーブル列やインデックスは無い
  (`db.get_raw_log_processed_at`は既存の`raw_logs`テーブルへのSELECTのみ)。既存の
  自己修復の仕組み(`_ensure_column`)にも変更を加えていないため、以前のバージョンで
  作られたDBファイルもそのまま(reindex不要で)使い続けられる。データを破壊的に変更する
  マイグレーションは今回のスコープに含まれていない。

## レビュー修正(3回目, 2026-08-24)

2回目のレビュー修正(コミット `19b5030`)に対する3回目のレビューで、Phase 2の設計自体は
合格としつつ、Phase 3へ進む前に2件の修正を求められた。

1. **reconcileが現在のclassifierに依存していた問題**: 2回目の修正で実装した
   `reconcile._repair_one()` は、不整合を見つけたraw_logについて
   `classify.classify(raw_log.text)` を再実行し、「現在の」分類結果でMemory化対象
   だったかどうかを判断していた。これは将来classifierの実装が変わった場合に
   過去の処理結果を誤って再解釈してしまう(指示書25章: 過去に確定した処理結果は
   Markdownが正本であり、現在の実装で再解釈しない、という原則に反する)。
   具体的には、(a) 旧classifierがmemory-worthyと判定してMemory Markdownを書いた
   直後にクラッシュした場合、新classifierがnot-memory-worthyだと既存のMemory
   Markdownを復元し損なう、(b) 逆に旧classifierがnot-memory-worthyと判定して
   正常にchat処理済みだったraw_logを、新classifierがmemory-worthyだと判定する
   ようになると「Memoryが無い異常事態」と誤検出してReconcileErrorを出しうる、
   という2方向の問題があった。
   修正として、`reconcile.py`はclassifierを一切呼ばないように変更した。
   raw_log_idから決定的に導出されるmemory_id(`ids.derive_memory_id`)で
   `memory_io.find_existing()` を呼び、既存Memory Markdownが見つかればそれを
   (現在のclassifierの判断に関係なく)無条件に正として復元する。見つからない
   場合は、raw_log自身のfrontmatterに記録された`processing_outcome`
   (当時の実際の処理結果。新設のメタデータ、後述)を見て判断する:
   `"memory"`なのにMemoryが無ければ矛盾としてReconcileErrorを送出し、
   `"chat"`、またはこのメタデータ自体を持たない旧形式のraw logであれば、
   Memoryが無いことをそのまま正常(または安全側のフォールバック)として受け入れ、
   ReconcileErrorにも新規Memory生成にもしない。
   これに伴い、Raw Logのfrontmatterへ最小限の処理メタデータを追加した:
   `processing_outcome`(`"memory"` | `"chat"`)と、Memory化された場合の
   `memory_id`。`raw_log_io.mark_processed()` がMemory処理の結果と同時に書き込む。
   Raw Log本文(body)は一切変更していない。**後方互換性**: 旧形式のraw log
   (このフィールドが導入される前に処理されたもの)には存在しないため、
   `read_raw_log()`は`.get()`でNoneにフォールバックする。呼び出し側
   (`reconcile._repair_one`)もNoneを「chatと同様、安全側」として扱うため、
   旧形式のraw logに対しても壊れずに動く。SQLite側のスキーマは変更していない
   (このメタデータはMarkdownにのみ持たせ、SQLiteは引き続きMarkdownの写しのまま)。
2. **reconcileがdaily_logsを復旧対象に含めていなかった問題**: 通常processでは
   Daily Log MarkdownへのAppendがMemory処理より先に行われるため、
   「Daily Markdown作成済み → Memory作成済み → Raw processed_at更新済み →
   SQLite commit直前クラッシュ」という窓では、Daily Markdownは存在するのに
   対応するSQLite `daily_logs` 行が存在しない状態になりうる(raw_logs/memoriesと
   同じ種類の不整合)。`reconcile.py`に小さなヘルパー`_reconcile_daily_log()`を
   追加し、`_repair_one()`から各raw_logの日付に対応するDaily Markdownの有無を
   確認して、存在すれば`db.upsert_daily_log()`で復元するようにした(`reindex()`が
   daily_logsを復元する際と同じ、ファイルの`updated_at`/`file_path`を使う方式)。
   日付単位のupsertなので、同じ日に複数のraw_logが修復対象になっても冪等に動く。
   `reconcile.py`を巨大化させないよう、この処理は独立した小さな関数に分離した。

`test_process_all_reconcile_restores_existing_memory_even_if_classifier_now_disagrees`
(必須テストA)と `test_process_all_reconcile_does_not_fabricate_memory_when_classifier_now_disagrees`
(必須テストB)を`test_pipeline.py`に追加し、classifierを差し替えた状態でも
reconcileが正しく動く(かつAではclassify.classify自体が一切呼ばれないことも
明示的に確認する)ことを検証した。既存の12ステップreconcileテスト
(`test_process_all_auto_reconciles_raw_log_processed_in_markdown_but_never_committed_to_sqlite`)
はdaily_logsの復旧確認を含むよう拡張した。`test_reconcile.py`は、以前の
「Markdown上processed_at済みなら常にReconcileError足りうる」という前提のテストを、
新しい判断基準(Memory実在の有無・processing_outcome)に合わせて書き直した。

## レビュー修正(4回目, 2026-08-25。Phase 2最後の修正)

`pipeline._process_one()` が、未処理のraw_logを処理する際に「既存Memoryの有無の
確認」より先に `classify.classify()` を実行していた問題を修正した(Phase 2の
最後のレビュー指摘)。

以前の順序では、not is_memory_worthyの場合に既存Memoryの確認すら行わずreturnして
いたため、次のクラッシュ復旧シナリオでMarkdownと処理結果が矛盾しえた: 旧classifier
がmemory-worthyと判定してMemory Markdownを書いた直後、raw_logのmark_processedより
前にクラッシュする(raw_logはまだunprocessed) → classifierが更新される →
同じraw_logを再processすると、新classifierの判定だけでchatとして処理済みになり、
既に存在するMemory Markdownが見捨てられる(SQLiteには反映されず、
processing_outcome="chat"なのにMemory Markdownは実在する、という矛盾状態が
生まれる)。

**不変条件**: raw_log_idから決定的に導出されるmemory_id
(`ids.derive_memory_id`)でMemory Markdownが既に存在する場合、`_process_one()`は
classifierを一切呼ばず、既存Markdownを常に正として再利用する。classifierが呼ばれる
のは、対応するMemory Markdownがまだ存在しない場合に限る。これはreconcile.pyが
3回目の修正で採用したのと同じ原則(過去に確定したMarkdownを現在のclassifierで
再解釈しない)を、通常のprocess経路にも一貫して適用したもの。

必須テスト`test_process_all_does_not_downgrade_existing_memory_to_chat_when_classifier_changes`
(`test_pipeline.py`)を追加し、上記のクラッシュ復旧シナリオを再現した上で、
classifierが差し替えられても既存Memoryが再利用され、かつ`classify.classify()`
自体が一切呼ばれないこと(呼ばれたらテスト自体を失敗させる実装で保証)、
Markdown/Raw Log/SQLiteの内容が一致すること、`reindex`後も状態が変わらないことを
確認している。

## 実施した検証

- `pytest tests/` — **94件、すべてPASS**(3回目のレビュー修正時点の93件 +
  今回(4回目)の新規1件
  `test_process_all_does_not_downgrade_existing_memory_to_chat_when_classifier_changes`。
  既存テストの削除・置き換えは無い)。
  - 3回目のレビュー修正時点の93件(2回目のレビュー修正時点の89件 + 3回目の
    新規4件。既存テストの削除・置き換えは無い。ただし`test_reconcile.py`の1件は、
    reconcileの判断基準そのものが変わったことに伴い、同じ懸念を検証する新しい
    アサーションに書き直した)は、そのまま維持。
  - 新規4件の内訳: 分類ロジック変更をまたぐreconcileの復旧テスト2件(必須テストA/B、
    `test_pipeline.py`)、`reconcile_processed_raw_logs()`単体でのフォールバック
    振る舞いを確認する2件(`test_reconcile.py`)。
  - 2回目のレビュー修正時点の89件は削除・置き換えなしでそのまま維持
    (`test_reconcile.py`の1件のみ、上記の理由で新しい判断基準に合わせて書き直し)。
  - 新規20件の内訳: 候補探索の200件上限撤廃を201件規模で確認する2件
    (`test_db_entities_links.py`)、`vault.write_text_atomic`の原子性・Windows安全性・
    一時ファイル衝突回避を確認する6件(`test_vault.py`)、`find_existing`のVault全体
    検索と重複検出・legacy entityのconfidenceを確認する6件(`test_memory_io.py`)、
    分類ロジック変更をまたぐクラッシュ復旧シナリオ1件と12ステップの
    reconcile障害注入テスト1件(`test_pipeline.py`)、`reconcile_processed_raw_logs()`
    単体の振る舞いを確認する4件(`test_reconcile.py`)。
  - 1回目のレビュー修正時点の69件(従来の51件 + 1回目レビュー修正での新規18件)は
    削除・置き換えなしでそのまま維持。
- 2回目のレビュー修正後も、`add` → `process`(entity抽出・link生成込み)→ `search` →
  `reindex` の一連の流れを実際にPython APIで実行し、Markdown(frontmatterの
  `entities`/`entity_details`/`links`/`link_details`)とSQLite(`memories`/
  `memory_entities`/`links`テーブル)の内容が一致すること、`reindex`後も同じ内容が
  復元されることを実データで確認した。
  - 従来の51件(Phase 1の25件 + Phase 2の26件)は、削除せず維持または内容を修正して
    引き継いだ。**削除・置き換えたのは、修正対象のバグの挙動そのものをテストしていた
    3件のみ**(`test_same_entity_creates_link_and_outranks_same_topic` /
    `test_max_links_per_memory_cap` / `test_list_active_memory_signals_excludes_given_id`)。
    いずれも同じ観点を検証する修正後版に置き換えており、カバレッジは失っていない
    (詳細はgit差分参照)。
  - 新規18件: Entityのconfidence算出(`test_entity_extract.py`)、confidenceに基づく
    リンク強度の逆転可能性(`test_linking.py`)、DB側候補探索が古いMemoryも見つけること
    (`test_db_entities_links.py`)、reindexでのlink.created_at完全一致と後方互換
    フォールバック、そして**最優先項目である障害復旧テスト2件**
    (`test_process_recovers_from_crash_after_memory_write_without_duplicating`:
    Memory書き込み後・DB反映前のクラッシュ、
    `test_process_recovers_from_crash_before_raw_log_marked_processed`:
    DB反映後・raw_log処理済みマーク前のクラッシュ)を `test_pipeline.py` に追加した
    (`monkeypatch`で`db.upsert_memory`/`raw_log_io.mark_processed`を1回だけ失敗させる
    方式。本番コードに例外注入用のフックは追加していない)。
- 指示書37章の完成条件(`add` → `process` → `search`)、およびentity/link生成を含む
  一連の流れを実際にCLIで実行し、生成されたMarkdown(frontmatterの `entities` /
  `entity_details` / `links` / `link_details`)とSQLiteの中身を直接確認した。
  confidenceが期待通りの値(一般語"アプリ"は低く、"ナイキ"のような3文字語より
  さらに低い)になっていることも実データで確認済み。SQLite全消去→`reindex`後に
  links(created_at含む)/entities(confidence/method含む)が完全に一致することも
  実データで確認済み。
- Phase 1で作られた(reason列の無い)`links` テーブル、およびこのレビュー修正より前の
  (confidence/method列の無い)`memory_entities` テーブルを模したDBに対して実際に
  処理を実行し、どちらも自己修復(列追加)が機能してエラーにならないことを確認済み。
- 3回目のレビュー修正後、`add`(Memory化される入力・chatになる入力の両方)→
  `process` → `reindex` を実際にPython APIで実行し、Raw Logのfrontmatterへ
  `processing_outcome`("memory"/"chat")と(該当する場合)`memory_id`が正しく
  書き込まれること、SQLite `daily_logs` テーブルが正しく反映されることを実データで
  確認した。
- **Docker実機検証はしていません**(このプロジェクトはDockerを使わない設計)。
- 実際のObsidianアプリでVaultを開いての目視確認は**未実施**です(このセッションの環境に
  Obsidianが無いため)。

## 既知の限界

- Entity抽出はカタカナヒューリスティックのみ。confidence補正はあるが、人名・地名の
  漢字表記や、ひらがな/漢字の一般名詞は一切拾えない。
- `raw_log_io.mark_processed()` によるMarkdown更新と、そのprocessed_atをSQLiteへ
  反映する `db.upsert_raw_log()` の間は、依然として単一のトランザクションでは結ばれて
  いない(2つの別々のストレージ(ファイルシステムとSQLite)にまたがる書き込みを1つの
  atomicな操作にはできないため)。ただし2回目のレビュー修正により、この間にクラッシュ
  しても**放置されず自動的に自己修復される**ようになった: `process_all()` が呼ばれる
  たびに冒頭で `reconcile.reconcile_processed_raw_logs()` が実行され、
  「Markdown上processed_at済みなのにSQLiteが未反映」の状態を検出して修復する。以前は
  この不整合が`reindex`を手動実行するまで残り続けていたが、今はいずれ次回の通常運用
  (`process_all()`の実行)の中で自動的に解消される。
- Raw Log本体・Daily Logの書き込みも、2回目のレビュー修正でMemory Markdownと同じ
  `vault.write_text_atomic()`経由になった(以前は非atomicだった)。Raw LogはVault内で
  最も失ってはいけない原本であるため、書き込み途中のクラッシュに対する耐性を
  Memoryと同水準にした。
- reconcile(自動修復)は3回目のレビュー修正で、現在のclassifierを再実行せず
  Markdown(Memory実在の有無・raw_logのprocessing_outcome)だけで判断するように
  変更した。ただしこれは「processing_outcomeが記録されていて、かつ実際にはMemory
  Markdownが存在するのにprocessing_outcomeが"chat"のまま」というような、
  Markdown自体が矛盾した状態(通常のクラッシュ・再試行では起こり得ない、手動編集等の
  異常系)までは検出しない。Memoryが実在すれば常にそれを正として復元する設計のため、
  この特定の矛盾は実害無く(Memory側が優先される)解消されるが、明示的な検出・警告は
  行っていない。

## 今後(まだ実装していないもの)

### Vector Search Sprint 4A（外部レビュー待ち）

provider/profile/backend contract、canonical embedding document/hash、backend共通の
little-endian float32 BLOB cache、ExactScan reference backend、embedding用SQLite schemaを実装した。
通常の`reindex`はproviderを要求せず、embedding cacheを空の派生tableとして再生成する。
Windows spikeはsqlite-vec 0.1.9でPASSしたが、core dependency化や本番SqliteVecBackend、
Vector/Hybrid Searchはまだ実装していない。詳細は`docs/VECTOR_SEARCH_DESIGN.md`と
`docs/SQLITE_VEC_WINDOWS_SPIKE.md`を参照。

Vector backendのmutationはcanonical BLOBではなく派生indexだけを対象とし、API名も
`sync_upsert` / `sync_delete` / `clear_index`として区別する。ExactScanは独立indexを
持たないためこれらはno-opで、canonical cacheのlife cycleはDB repository側が管理する。
Embedding user configはseparator/camelCaseを正規化したcredential key検査を行い、未知の
nested fieldであってもAPI key/token/password/secret類の平文保存を拒否する。

### Vector Search Sprint 4B(2026-08-25、ユーザーによる外部レビューGO受領)

canonical embedding cacheは次の明示commandで管理する。通常の`reindex`は従来どおり
providerを呼ばず、embedding生成やnetwork accessを開始しない。

```bash
python brain.py embeddings status
python brain.py embeddings sync
python brain.py embeddings rebuild
```

syncはactive Memoryをkeyset paginationで読み、canonical document hashがmissing/staleの
Memoryだけをprovider batchへ送る。成功したbatchは都度commitするため、中断後の再実行では
hash/profile一致分をskipして残件から再開する。新profileはpartial cacheをstagingとして保持し、
全件生成とbackend buildが成功した後だけactive pointerを切り替える。

Sprint 4Bではproduction providerを同梱していないため、`status`は設定だけで利用できるが、
標準配布のまま`sync`/`rebuild`を実行すると「provider is not installed」という明示errorになる。
orchestrationはoffline deterministic fakeで検証しており、provider adapterは次の承認済みSprintで
別途追加する。`apikey`/`APIKey`/`private_key`/`privateKey`も平文credentialとして拒否する。

staging profile生成中はcanonical BLOBだけを保存し、現在activeなbackend indexへincremental
upsertしない。同一active profileかつbackend stateが完全にreadyの場合だけincremental同期する。
またtitle/content変更時はSQLite triggerが既存embeddingを即時invalid化し、ExactScanはvalid rowを
top-K計算前にSQLで限定する。したがってsync前やprovider失敗中にstale vectorは検索候補にならない。

### Vector Search Sprint 4C(外部レビュー待ち)

「Sprint 4Cの目的」節の「使い方」に実際のコマンド例がある。設計上のポイントのみここに記録する。

- **Hybrid lexical channelは`search.search()`を呼ばない**。DB層に新設した
  `db.search_lexical_candidates()`(BM25のみ、importance/confidence/recency未適用)を使う。
  metadata weightingの式そのものは`search.py`から`retrieval_weights.py`へ抽出し、lexical検索と
  Hybridの両方が同じ`metadata_multiplier()`を参照する(実装が分岐しない)。抽出前後で
  `search()`の出力が変わっていないことは`tests/test_search.py`のcharacterization testで固定した。
- **Vector Primary Search**(`vector_search.py`)は、query embeddingの検証(dimension/finite/
  非zero/normalized契約)と、activeなprofile・backendの両方が完全に`ready`であることを確認する
  availability gateを経てから`VectorIndexBackend.search()`を呼ぶ。条件を満たさない場合は
  `VectorSearchUnavailableError`を送出し、lexical検索へ黙ってfallbackしない。
- **Hybrid Primary Search**(`hybrid_search.py`)はpure lexical候補とpure vector候補のunionを
  Weighted Reciprocal Rank Fusion(既定 lexical 0.6 / vector 0.4 / `rrf_k=60`、
  `RetrievalWeights`に集約)で融合し、`metadata_multiplier`をfusion後に1回だけ適用する。
  ranking自体は軽量なimportance/confidence/event_dateだけで行い、確定した上位N件のIDにだけ
  title/content/topics/entitiesを取得する(候補全件の本文を読み込まない)。同点はfinal_score→
  best channel rank→event_date→memory_idの順で決定的に解決する。
- Sprint 4Bの実装中に見つかった**embedding consistency race**(providerへの問い合わせ中に
  Memoryのtitle/contentが変更されると、古い本文のvectorがvalidとして保存されてしまいうる問題)
  もこのSprintで修正し、続くfinal hardeningでさらに完全に閉じた。最初の修正は書き込み直前に
  Memoryを再読込し、現在のcontent_hashと一致する場合だけvalid保存する、というものだったが、
  その再読込自体はただの`SELECT`で書き込みlockをまだ持っておらず、「再読込」と「書き込み」の
  間にもごく短いrace windowが残っていた。final hardeningでは、この再読込の**前**に
  `BEGIN IMMEDIATE`で書き込みlockを取得し、再読込・content_hash確認・canonical cache書き込み・
  (incremental同期時は)backend `sync_upsert`を同じ1つのtransaction境界の中で行うことで、
  この隙間も塞いだ。providerへの問い合わせそのものはtransaction外のまま(長時間lockを
  保持しない)。content_hashが不一致(または対象MemoryがactiveでなくなっていたらNoneが返る)
  場合は何も書き込まず、次回syncが現在の本文を前提に再処理する。staging profileのactivate
  直前にも`ready == total_active`を再確認し、レースで一部がskipされたまま不完全なindexが
  activeになることを防ぐ。
- **Hybrid用lexical candidateのtie-break**(`db.search_lexical_candidates()`)も
  final hardeningで決定的にした。以前は`ORDER BY score`のみで、`bm25()`スコアが同点の場合
  (内容がほぼ同じMemory等)の順序が未規定だった。`lexical_rank`はWeighted RRFとHybridの
  best-channel-rank tie-breakへ直接影響するため、`ORDER BY score ASC, m.id ASC`という
  明示的なtie-breakを追加した。`db.search()`/`search.search()`(通常のlexical検索、後方互換
  対象)は変更していない。

production embedding provider(sentence-transformers/OpenAI/Ollama等)と`SqliteVecBackend`本番
adapterはSprint 4Cでも意図的に未実装のまま(`ExactScanBackend` + fake/recording providerのみで
検索architecture自体を完成させる方針)。

### Vector Search Sprint 4D(実装・validated、Windows benchmark pending — 全体は未完了)

Sprint 4Dは以下の状態(**Sprint 4D: implemented and validated; external review pending。
Windows ExactScan benchmarkが完了するまでSprint 4D全体としては未完了**、
Phase 4 Vector Retrieval Core / Production activationについても同様に自己COMPLETE宣言は
しない)。

- **Associative Retrieval統合**: **reviewed GO**。`retrieval.py`の1-hop展開ロジックを
  `retrieve_from_primary()`として抽出し、primary結果の型に依存しない(`memory_id`属性
  さえあればよい)Protocol/Genericにした。既存の`retrieve()`(plain lexical検索用)は
  この`retrieve_from_primary()`を呼ぶよう委譲するだけになり、挙動・出力は変更していない。
  CLI `search --vector --related` / `search --hybrid --related` は、Vector/Hybrid
  Primaryの結果をそのまま`retrieve_from_primary()`へ渡して1-hop関連Memoryを取得し、
  従来の`--related`単体時と同じ書式で表示する。
- **CLI hardening**: **reviewed GO**。`--related-limit`に負値を指定した場合、embedding
  config/provider/vector検索を一切開始せずに`[NG]`errorを返すようにした
  (plain/`--vector`/`--hybrid`すべて同一契約)。以前は`--vector`/`--hybrid`との
  併用時にPrimary結果を表示してから初めてvalidation errorになっていた。
- **Failure/recovery/migration/corruption validation**: **reviewed GO**。provider途中
  failure resume、profile switch failure時の旧active維持、backend index損失からの
  `rebuild_backend()`復旧、stale MemoryのVector除外/Hybrid lexical経由残存/resync復旧、
  inactive/delete除外、**SQLite全削除→reindex→resync**の完全復旧、legacy schema
  self-heal(複数gapを同時に持つ実DB fixtureで検証)、malformed/破損cacheのfail-safeを
  実DB fixtureで確認した。詳細は`docs/VECTOR_RECOVERY_VALIDATION.md`。
- **Windows benchmark**: **Linux substitute run: completed / Windows実機run: pending**。
  `scripts/vector_benchmark.py`(1k/10k Memories × dimension 384/768、`ExactScanBackend`
  reference/fallback専用、production providerなし)。外部レビューでbenchmark scriptに
  3件の修正が必要と指摘され、今回対応した: (1) module top-levelの`import resource`が
  Windowsで失敗する問題(`try`/`except ImportError`でplatform-independentに)、
  (2) 旧`G_hybrid_plus_related`は実際にはrelated expansion overheadのみの計測だった
  問題(hybrid_search呼び出しがtimed loop外だったため)を、`G_related_expansion_only`
  として維持しつつ、新設の`H_hybrid_plus_related_end_to_end`(毎sample内で
  hybrid_search+retrieve_from_primaryを同一timed callableで実行)で真のend-to-end値を
  計測、(3) synthetic `event_date`の手計算がFeb 30等invalid dateを生成しうる問題を
  `date + timedelta`で修正。修正後にLinuxで再測定した値も追加した(捏造ではなく実測)。
  **このセッションはLinuxのリモート実行環境のためWindows実機での正式benchmarkはまだ
  未実施**。詳細・両方の実測値は`docs/VECTOR_WINDOWS_BENCHMARK.md`
  (「Windows official run」セクションはpendingのまま)。

production embedding providerと`SqliteVecBackend`本番adapterは引き続き未実装であり、
上記のいずれも「production Vector Search性能/完了」を意味しない。

### 次にやるべきPhase

Phase 1〜3(Memory Foundation、Automatic Memory Worker、Retrieval)は完了している。
Vector Search(Phase 4)はSprint 4A〜4Dまで実装済み。Sprint 4Dのうち associative
integration・CLI hardening・failure/recovery/migration validationはreviewed GO済みだが、
**Windows ExactScan benchmarkが未実施のため、Sprint 4D全体としてはまだ完了していない**。
次に許可されるまでは、Sprint 4E相当のscope・production embedding provider・
`SqliteVecBackend`本番adapter・`ask`/LLM・Contradiction Detection・Memory Consolidation・
smartphone統合には進まない。
