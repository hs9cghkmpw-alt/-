# Brain Twin 2.0 — Phase 1 + Phase 2: Memory Foundation & Automatic Memory Worker

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
│  ├ pipeline.py          # add / process / reindex の実処理
│  ├ search.py            # 簡易Hybrid Retrieval
│  └ cli.py               # argparseによるコマンド定義
├ tests/                  # pytest (69 tests)
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

## 実施した検証

- `pytest tests/` — **69件、すべてPASS**。
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
- **Docker実機検証はしていません**(このプロジェクトはDockerを使わない設計)。
- 実際のObsidianアプリでVaultを開いての目視確認は**未実施**です(このセッションの環境に
  Obsidianが無いため)。

## 既知の限界

- Entity抽出はカタカナヒューリスティックのみ。confidence補正はあるが、人名・地名の
  漢字表記や、ひらがな/漢字の一般名詞は一切拾えない。
- `raw_log_io.mark_processed()` によるMarkdown更新と、そのprocessed_atをSQLiteへ
  反映する `db.upsert_raw_log()` の間はトランザクションで結ばれていない。この間に
  クラッシュすると、SQLite側の `raw_logs.processed_at` が実際より古い値のまま残る
  ことがある(Markdown側は正しく更新済み)。Memoryの重複生成には繋がらないが、
  `reindex` するまでSQLiteの表示上「未処理」に見える可能性がある、という限定的な
  既知の不整合として明記しておく。
- Raw Log本体・Daily Logの書き込みは(Memory書き込みとは異なり)原子的にしていない。
  これらは「同じ入力からの再試行で重複が生じる」という失敗モードを持たないため
  (`add`は常に新規入力、Daily Logへの追記はraw_log_id単位で冪等)、今回のスコープには
  含めなかった。

## 今後(まだ実装していないもの)

指示書のPhase 2の残り(自動ラベリングの高度化、より高度なEntity抽出)、および
Phase 3以降: Contradiction Detection・Memory Consolidation・Vector Search・
LLM Provider Interface・スマホ連携・`ask`コマンド、など。

### 次にやるべきPhase

指示書28章のPhase分割に沿うなら、次は **Phase 3(Retrieval)** の残り、具体的には
指示書17章「二段階想起(Associative Retrieval)」——`search` の結果からLinkを辿って
関連Memoryも合わせて提示する機能——が最も自然な続き。Phase 2で作った `links` テーブル
(`db.links_for_memory`)はこのために既に用意してある。次点は同じPhase 3の
「timeline検索」(event_dateでの絞り込み)。
