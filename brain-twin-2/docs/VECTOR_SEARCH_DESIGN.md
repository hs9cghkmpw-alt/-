# Vector Search Design（設計レビュー用）

Status: **design review pending**

Scope: Vector Searchの設計のみ。実装、`ask`、LLM回答生成、Contradiction Detection、
Memory Consolidationは含まない。

## 1. 目的と非目的

Phase 3で完成したPrimary検索（FTS5 + importance/confidence/recency）と1-hopの
Associative Retrievalを壊さず、意味的に近いMemoryをPrimary候補へ追加する。

守る境界は次のとおり。

- Markdown/VaultがMemoryのSource of Truth。
- embedding、vector index、model metadataはすべて削除可能な派生cache。
- embedding都合のfieldをMemory Markdownへ追加しない。
- Raw Log、Daily Logはembedding対象にせず、原文も変更しない。
- Embedding ProviderはLLM Providerと別interfaceにする。
- 既存の`search()`と`search --related`の既定動作は維持する。
- Vector機能が未設定・一時故障でもlexical searchとreindex本体は利用できる。

## 2. 推奨アーキテクチャ

```text
Markdown Memory
      │ read/build canonical embedding document
      ▼
EmbeddingService ── EmbeddingProvider
      │                    ├ remote provider（将来）
      │                    └ local/offline provider（将来）
      ▼
EmbeddingRepository (SQLite BLOB cache + profile/hash)
      │
      ▼
VectorIndexBackend
      ├ SqliteVecBackend（推奨、Windows spike合格後）
      └ ExactScanBackend（互換fallback / 小規模 / test）

query
  ├ Lexical candidate channel (FTS5)
  └ Vector candidate channel (query embedding + KNN)
             │
             ▼
       HybridPrimaryRanker
             │ Primary Memory
             ▼
       Associative 1-hop expansion（既存）
```

重要なのは「embedding生成」と「近傍検索backend」を分離すること。モデル交換は
Embedding Provider/profileの問題であり、sqlite-vec交換はVectorIndexBackendの問題である。

## 3. Embedding Provider Interface

`brain_twin/embedding_provider.py`に、特定SDKをimportしないProtocolと値型を置く。

```python
@dataclass(frozen=True)
class EmbeddingProfile:
    provider_id: str       # 例: sentence_transformers / openai / ollama
    model_name: str
    model_revision: str    # remote APIも固定可能な値。未知なら明示的に"unknown"
    dimension: int
    normalized: bool
    document_template_version: int

class EmbeddingProvider(Protocol):
    @property
    def profile(self) -> EmbeddingProfile: ...
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
```

- document/queryを分ける。IR向けmodelのquery/document prompt差をprovider内部で扱える。
- batch APIを必須とし、1件も長さ1のbatchとして扱える。
- 戻り値の件数、dimension、finite値、必要ならL2 normをservice層で検証する。
- providerが返すdimensionと設定値が違えば保存せず`EmbeddingDimensionError`。
- 空入力、認証/設定不備、恒久的model不在は`EmbeddingConfigurationError`。
- timeout/rate limit/一時的ローカルmodel停止は`EmbeddingTransientError`として、batch単位で
  bounded retry（指数backoff、最大回数中央設定）可能にする。
- 一部batchだけ成功した場合は成功分をcommitし、未完IDを再実行可能にする。Memory作成を
  rollbackしない。
- API keyやmodel cache pathをDB/Markdownへ保存しない。

`profile_fingerprint`は上記profileの安定JSONをSHA-256化する。provider名だけでなく
revision、dimension、normalization、document templateも含める。

### Canonical embedding document

Sprint 1ではversion 1を次に固定する。

```text
title: {Memory.title}
content: {Memory.content}
```

type/topics/entities/links/statusは含めない。検索ranking用metadataや派生情報の変更だけで
高コストな再embeddingを起こさず、本人のMemory本文を意味表現の中心にするためである。
組み立ては`EmbeddingDocumentBuilder`へ集約し、`document_template_version`を上げたときだけ
全再生成する。`content_hash`はUTF-8化したcanonical documentのSHA-256とする。

## 4. Vector保存方式の比較

| 方式 | 長所 | 短所 | 判断 |
|---|---|---|---|
| SQLite BLOB + Python exact scan | 標準SQLiteだけで再構築容易、testしやすい、Windows差が小さい | 全件読込/O(ND)、大量Memoryで遅い | fallback/testとして採用 |
| sqlite-vec `vec0` | SQLiteと同じ運用境界、KNNをSQLで実行、単一C extension、Python packageとWindows buildあり | loadable extension、Python同梱SQLite版、配布wheelの組合せ検証が必要。ANN機能はversion依存 | Windows spike合格を条件に推奨backend |
| sqlite-vss/Faiss | 高速な近傍探索 | Faiss由来の依存と配布が重く、Windows運用と再構築が複雑 | 初期採用しない |
| hnswlib/FAISS等の別Python index file | 大規模ANNが速い | SQLiteとの二重transaction、index file lifecycle、Windows wheel、削除/更新整合性が増える | 将来の規模計測後にadapter追加 |
| 外部vector DB | 水平拡張、運用機能 | server/認証/同期が必要でoffline・単一PC方針に過剰 | 採用しない |
| JSON/float配列をMarkdownへ保存 | Vaultだけで完結 | Markdownを巨大な派生値で汚し、model交換時に大量差分 | 禁止 |

推奨は、**SQLiteの通常tableをembedding cacheの管理面、sqlite-vecを検索面**とする。
sqlite-vecだけを唯一の保存先にせず、profile/hash/生成状態を通常tableで検査可能にする。
ただしvector値の二重永続化は避け、採用backendがsqlite-vecならvector本体は`vec0`、
ExactScanBackendなら`memory_embeddings.embedding_blob`を使う。backendはDB metadataへ記録する。

sqlite-vec公式資料ではPyPI導入とWindows対応が案内されている一方、loadable extensionと
Python同梱SQLiteの互換性は環境依存である。そのためSprint 1にWindows 11 + projectの
対応Python版でinstall/load/insert/query/delete/rebuildを検証するGateを置く。

## 5. DB schema案

通常SQLite table（概念DDL）:

```sql
CREATE TABLE embedding_profiles (
    fingerprint TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    normalized INTEGER NOT NULL CHECK (normalized IN (0, 1)),
    document_template_version INTEGER NOT NULL,
    backend TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE memory_embeddings (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    profile_fingerprint TEXT NOT NULL REFERENCES embedding_profiles(fingerprint),
    content_hash TEXT NOT NULL,
    embedding_blob BLOB,       -- ExactScanBackend時のみ。sqlite-vec時はNULL可
    vector_key INTEGER,        -- vec0 row mapping。backend非依存APIの内部値
    embedded_at TEXT NOT NULL,
    PRIMARY KEY (memory_id, profile_fingerprint)
);

CREATE INDEX idx_memory_embeddings_profile
ON memory_embeddings(profile_fingerprint);

CREATE TABLE embedding_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    active_profile_fingerprint TEXT REFERENCES embedding_profiles(fingerprint),
    backend TEXT NOT NULL,
    backend_schema_version INTEGER NOT NULL
);
```

sqlite-vec tableはdimensionをDDLへ埋める必要があるため、active profile変更時に
`memory_vector_index`をdrop/recreateする。正確な`vec0` DDLとtext primary key対応は
採用versionをpinしたWindows spike後に確定する。SQL文字列生成はdimensionを整数検証し、
任意文字列をidentifierへ展開しない。

vectorはfloat32、cosine用にL2 normalizeを標準とする。dimension×4 bytes/Memoryに加え
index overheadを容量見積りへ使う。SQLite DB全体が消えてもMarkdownから再生成できる。

## 6. Invalidationとmigration

embeddingが有効なのは次がすべて一致するときだけ。

1. `memory_id`
2. active `profile_fingerprint`
3. 現在のcanonical document `content_hash`
4. backend schema version

| 変化 | 動作 |
|---|---|
| title/content変更 | hash不一致のMemoryだけstale。再生成までvector channelから除外 |
| model/revision変更 | 新fingerprint。旧行を検索に使わず、新profileをbatch生成 |
| dimension/normalization/template変更 | 新fingerprint。vector tableをstaging再構築 |
| Memory inactive/archive | vectorは残っても検索時に`memories.status='active'`で除外。cleanup可能 |
| Memory削除 | FK cascade + backend delete |
| vector cache破損/欠落 | lexicalは継続。`embeddings rebuild`で再生成 |

既存DBは`CREATE TABLE IF NOT EXISTS`で非破壊追加する。既存Memory Markdownは変更しない。
legacy DBにはactive profileがないためVector機能をdisabledとみなし、起動時にmodel downloadや
全件embeddingを暗黙実行しない。profile切替はstaging profile/indexを完成させてから
短いtransactionでactive pointerを切替え、途中失敗時は旧profileを維持する。

## 7. APIとmodule構成案

```text
brain_twin/
  embedding_provider.py   # Protocol、profile、typed errors（SDK非依存）
  embedding_document.py   # canonical document + content hash
  embedding_service.py    # batching、validation、retry、sync/rebuild orchestration
  vector_index.py         # VectorIndexBackend Protocol、result型
  vector_sqlite_vec.py    # optional sqlite-vec adapter
  vector_exact.py         # BLOB exact cosine fallback/test backend
  hybrid_search.py        # channel fusion + metadata policy
  db.py                   # schema/query、embedding metadata repository
  search.py               # 既存search()は変更しない
  retrieval.py            # Primary受取後の既存1-hop policy
```

公開API案:

```python
vector_search(config, query, provider, *, limit=20) -> list[VectorResult]
hybrid_search(config, query, provider, *, limit=20) -> list[HybridResult]
retrieve_from_primary(conn, primary, *, related_limit=20) -> RetrievalResult
```

- 既存`search()` / `search_with_config()`はそのままlexical互換APIとして残す。
- 既存`retrieve()`は既定で現行lexical Primaryを使う。
- 将来`retrieve_hybrid()`は`hybrid_search()`のPrimary結果を
  `retrieve_from_primary()`へ渡す。Associative logicを複製しない。
- CLIは実装Sprintで明示opt-in（例:`search QUERY --vector` / `--hybrid`）。model未設定時に
  従来searchを壊さない。`ask`は作らない。

## 8. Hybrid ranking案

BM25とcosineの生値は尺度と向きが異なるため、初期版は学習やquery単位min-maxではなく
**Weighted Reciprocal Rank Fusion (RRF)**を採用する。

```text
fusion = lexical_weight / (rrf_k + lexical_rank)
       + vector_weight  / (rrf_k + vector_rank)

final = fusion * metadata_multiplier(importance, confidence, recency)
```

- 初期値案: lexical 0.6、vector 0.4、`rrf_k=60`。値は`RetrievalWeights`一箇所へ集約。
- 各channelは`limit * candidate_multiplier`（初期3、上限あり）を取得してmemory_idでunion。
- channelに不在ならその項は0。exact scoreは説明/diagnostic用に保持する。
- metadata multiplierは現行式を共通関数へ抽出する実装案。ただし既存`search()`の結果を変えない
  characterization testを先に置く。
- 同点はbest channel rank、event_date、memory_id等の明示的keyで決定的にする。
- weight tuningは固定fixtureと実Vaultから匿名化した評価queryで行い、コード各所へ散らさない。

Vector導入後の順序は必ず次にする。

```text
lexical/vector hybrid primary retrieval
  -> Primary Memory dedupe/ranking
  -> existing outgoing+incoming associative 1-hop expansion
  -> Related limit/detail fetch
```

Relatedからvector検索したり2-hop展開したりしない。Link strengthとvector similarityも
初期版では混ぜず、Primary rankingとRelated rankingの説明可能性を維持する。

## 9. Data flow

### embedding sync

1. DBからactive Memoryのid/title/contentを軽量batch取得。
2. canonical documentとhashを作成。
3. active profileとhashが一致する行をskip。
4. stale/missingのみproviderへbatch送信。
5. shape/finite/normalizationを検証。
6. batch transactionでembedding cacheとvector backendをupsert。
7. 失敗batchを報告し、再実行で続行。Memory Markdownは一切書かない。

### query

1. lexical channelとquery embedding/vector channelを実行。
2. active Memoryだけを候補にする。
3. RRF + metadataでPrimaryを作る。
4. requested limitだけ詳細/Entityを取得。
5. `--related`なら既存1-hop expansionへ渡す。

query embeddingは短TTLのprocess内LRUを任意採用できるが、query本文を永続DBへ保存しない。

## 10. Reindex flow

既存`python brain.py reindex`がprovider/network不調で失敗する後方非互換を避ける。

1. `reindex`は従来どおりMarkdownからmetadata/FTS/entities/linksを完全再構築。
2. vector cacheは失われても正常。active profile設定だけ復元/再設定可能にする。
3. `python brain.py embeddings rebuild`または
   `python brain.py reindex --embeddings`を明示した場合だけ、Markdown由来Memoryをbatch embeddingし
   vector indexをstaging構築する。
4. 全batch成功後active indexを切替える。中断時は再開でき、lexical indexは完成状態を保つ。
5. `--embeddings`失敗は明確なnon-zeroと未完件数を返すが、Markdown/FTSをrollbackしない。

これにより「Vaultだけから全cacheを再生成可能」と「embedding providerがなくても基本機能を
復旧可能」を両立する。

## 11. 大量Memory時の性能

- provider batch size、DB read batch、commit batchを別設定にする。
- 全Memoryを一度にPythonへ保持せず、keyset paginationでstreamする。
- vector queryはtop KだけをDBから返し、全文取得はfusion後のtop Nだけにする。
- active status filterをKNN前後どちらで適用可能かsqlite-vec spikeで測定する。filter後取得で
  K不足になるbackendはoverfetchして補う。
- 目標計測点: 1k / 10k / 100k Memory、384/768 dimension、cold/warm query、rebuild throughput、
  DB容量、Windows CPU/RAM。
- ExactScanBackendは小規模とfallback向け。閾値を超えたら警告し、黙って大規模scanしない。
- ANNはsqlite-vecの安定版機能と実測が揃うまで必須にしない。adapterにより後から追加する。

## 12. Test plan

### provider contract

- document/query API、batch順序、空batch、件数不一致、dimension不一致、NaN/Inf。
- transient retry上限、permanent error非retry、部分batch再開。
- remote fakeとlocal fakeが同じcontract suiteを通る。

### persistence/invalidation

- Markdownにembeddingを書かない。
- title/content変更だけstale、metadata-only変更はversion 1では再生成しない。
- model/revision/dimension/template変更で旧vectorを検索しない。
- legacy DBの非破壊migration、cache全削除から再生成。
- inactive/deleted Memory除外、profile切替途中のrollback。

### backend contract

- sqlite-vecとexact backendで同じ既知vectorのtop K/order。
- insert/update/delete、dimension、empty index、large ID batch。
- Windows CI/spikeでextension load/unloadと対応SQLite versionを確認。

### ranking/retrieval

- lexical-only、vector-only、両方hit、重複dedupe、決定的tie。
- RRF weightとmetadata multiplierのcharacterization。
- 既存`search()`結果が完全一致。
- hybrid Primary後もoutgoing/incoming、Related dedupe、inactive、1-hop、limitを維持。
- top N確定前に全Memory本文をロードしない。

### reindex/recovery

- Vault -> metadata/FTS -> embeddings -> vector indexの完全再現。
- provider停止中も通常reindex/searchが成功。
- embedding rebuild中断・再開、model切替失敗時に旧active index維持。
- crash後にMarkdownを再解釈/変更しない。

## 13. Windows / offline-local移行

- sqlite-vec package/version、Python version、`sqlite3.sqlite_version`をpinして検証記録する。
- extension loadingは接続初期化の短い区間だけ許可し、load後すぐ無効化する。
- DLLを任意pathからロードせず、installed packageが返す検証済みpathだけを使う。
- sqlite-vecがloadできない環境はtyped capability errorを出し、設定によりexact backendへfallback。
- local provider実装はoptional dependency groupに分離する。`sentence-transformers`等をcore依存へ
  直ちに追加しない。
- model filesはVault/Git外のmodel cacheへ置き、初回downloadを暗黙実行しない。事前取得、
  offline mode、CPU device、batch sizeを設定可能にする。
- remoteからlocalへ変更するとprofile fingerprintが変わるだけで、DB/retrieval APIは同じ。
- 日本語/英語混在の実データ評価後にmodelを選ぶ。特定model名を設計段階で固定しない。

## 14. Sprint分割案

### Sprint 4A — contracts and Windows storage spike

- provider/backend Protocol、fake provider、canonical document/hash。
- schema migration案をtest DBで実証。
- sqlite-vecのWindows install/load/CRUD/KNN/rebuild benchmark。
- Gate: sqlite-vec採用確定、またはExactScanを初期backendに切替。

### Sprint 4B — rebuildable embedding cache

- DB repository、sync/rebuild、invalidation、resume、CLI管理command。
- local deterministic fakeでreindex完全復元を先に保証。
- production providerはまだ1種類に限定し、LLM interfaceは作らない。

### Sprint 4C — vector and hybrid primary retrieval

- `vector_search()`、weighted RRF `hybrid_search()`、中央weights。
- 既存search後方互換と本文遅延取得。
- CLI opt-inとdiagnostic component scores。

### Sprint 4D — associative integration and hardening

- hybrid Primaryを既存1-hop expansionへ接続。
- 10k以上のWindows benchmark、failure/recovery/migration test。
- 設計値を評価結果で調整し、Vector Search完了レビューへ提出。

## 15. 未解決事項（設計レビューで決める）

1. Windows spikeでpinするPython/sqlite-vec/SQLite version。
2. 初期production embedding providerと日本語評価dataset/query。
3. 初期modelのdimension、license、model revision固定方法、download容量。
4. sqlite-vecを必須dependencyにするかoptional extraにするか。
5. ExactScanBackendを何件まで許可するか。
6. lexical/vector初期weightとRRF candidate overfetch値。
7. `reindex --embeddings`と独立`embeddings rebuild`のCLI表面を両方持つか。
8. model profileを複数世代保持する期間とdisk cleanup policy。
9. remote provider利用時のprivacy確認・明示opt-in UX。

## 16. 採用条件

この文書のレビューGOだけではVector Search実装完了ではない。Sprint 4AのWindows spikeと
schema/provider contractレビューを通過してから実装へ進む。Phase 3の123テストを維持し、
各SprintでMarkdown正本・再構築性・lexical fallbackを証明する。

## 17. 参照した一次資料

- [sqlite-vec installation](https://github.com/asg017/sqlite-vec/blob/main/site/getting-started/installation.md)
- [sqlite-vec Python integration](https://alexgarcia.xyz/sqlite-vec/python.html)
- [sqlite-vec compilation / Windows DLL](https://alexgarcia.xyz/sqlite-vec/compiling.html)
- [Sentence Transformers encode API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)
