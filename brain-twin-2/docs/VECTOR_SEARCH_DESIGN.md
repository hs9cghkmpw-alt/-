# Vector Search Design（設計レビュー用）

Status: **Sprint 4A complete. Sprint 4B complete. Sprint 4C implemented; external review pending**

Scope: Vector Searchの設計のみ。実装、`ask`、LLM回答生成、Contradiction Detection、
Memory Consolidationは含まない。

## 1. 目的と非目的

Phase 3で完成したPrimary検索（FTS5 + importance/confidence/recency）と1-hopの
Associative Retrievalを壊さず、意味的に近いMemoryをPrimary候補へ追加する。

守る境界は次のとおり。

- Markdown/VaultがMemoryのSource of Truth。
- Embedding構成のSource of TruthはSQLite外の明示的なuser config。
- embedding、vector index、SQLite内のprofile/state写しはすべて削除可能な派生cache。
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

### 3層のSource of Truth

| 層 | Source of Truth | 内容 |
|---|---|---|
| Memory | Markdown/Vault | title、content、type等のMemory本体 |
| Embedding configuration | Git管理外のuser config file | provider、model、immutable revisionまたはgeneration key、dimension、normalized、document template version、backend等の非秘密設定 |
| Derived cache | SQLite | metadata/FTS、embedding profileの写し、embedding vector、vector index、build状態 |

user configの既定path案はWindowsで`%APPDATA%\BrainTwin\config.toml`、Linuxで
`$XDG_CONFIG_HOME/brain-twin/config.toml`（未設定時`~/.config/brain-twin/config.toml`）、
macOSで`~/Library/Application Support/BrainTwin/config.toml`とする。`BRAIN_TWIN_CONFIG`で
明示pathを上書き可能にする。projectの`data/`配下には置かない。data directoryと一緒に
消去されると構成まで失うためである。path解決は小さな標準ライブラリ実装を第一候補とし、
この目的だけで依存を増やさない。

config fileへ保存してよいのは非秘密設定だけとする。API key/token/passwordは保存せず、
環境変数、OS credential store、またはprovider SDKの安全な認証機構から実行時に取得する。
configには秘密値そのものではなく、必要なら`credential_source = "environment"`のような
取得方式だけを書く。権限を絞っても平文secret保存を許可しない。

## 3. Embedding Provider Interface

`brain_twin/embedding_provider.py`に、特定SDKをimportしないProtocolと値型を置く。

```python
@dataclass(frozen=True)
class EmbeddingProfile:
    provider_id: str       # 例: sentence_transformers / openai / ollama
    model_name: str
    model_revision: str | None  # providerが保証するimmutable revision
    profile_epoch: str | None   # revision非公開時にuser configで明示する世代key
    embedding_contract_version: int
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

production profileは、providerが保証するimmutableな`model_revision`、またはuser configで
明示する非空の`profile_epoch`を必須とする。`model_revision="unknown"`だけのproduction起動は
configuration errorにして、silent staleを許さない。revisionを公開しないremote providerでは、
利用者が`profile_epoch`（例:`2026-08-provider-refresh-1`）を更新することで意図的に全再生成する。
さらにprovider adapterやquery/document prompt、前処理契約が変わる場合は
`embedding_contract_version`を実装側で上げる。

`profile_fingerprint`はprofileの安定JSONをSHA-256化する。provider/model、immutable revision
またはprofile_epoch、dimension、normalization、document template version、
embedding contract versionを含める。Vector backendは含めない。同じembeddingを
ExactScanBackendとSqliteVecBackendのどちらでも利用できるためである。test専用fakeだけは
明示的な固定generation keyを使え、production validationを暗黙に迂回しない。

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

推奨は、**SQLiteの通常tableをcanonical embedding cache、sqlite-vecを検索index**とする。
`memory_embeddings.embedding_blob`はbackendに関係なく常にcanonical float32 vectorを保持する。
SqliteVecBackend採用時はvec0にもvectorが複製されるが、これは意図的な二重保存である。
ExactScan↔sqlite-vec切替、provider停止中のbackend変更、remote embedding再課金の回避、
vec0破損時のindexのみ再構築を優先する。embedding BLOBもvec0もSQLiteと共に消えてよい
derived cacheであり、Markdown + user config + providerから完全再生成可能である。
active backendはuser configが正本で、SQLiteにはbuild済みbackend状態の派生写しだけを記録する。

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
    model_revision TEXT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    normalized INTEGER NOT NULL CHECK (normalized IN (0, 1)),
    document_template_version INTEGER NOT NULL,
    embedding_contract_version INTEGER NOT NULL,
    profile_epoch TEXT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        (model_revision IS NOT NULL AND trim(model_revision) != '' AND lower(trim(model_revision)) != 'unknown')
        OR (profile_epoch IS NOT NULL AND trim(profile_epoch) != '' AND lower(trim(profile_epoch)) != 'unknown')
    )
);

CREATE TABLE memory_embeddings (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    profile_fingerprint TEXT NOT NULL REFERENCES embedding_profiles(fingerprint),
    content_hash TEXT NOT NULL,
    embedding_blob BLOB NOT NULL, -- 全backend共通canonical little-endian float32 cache
    embedded_at TEXT NOT NULL,
    PRIMARY KEY (memory_id, profile_fingerprint)
);

CREATE INDEX idx_memory_embeddings_profile
ON memory_embeddings(profile_fingerprint);

CREATE TABLE active_embedding_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    active_profile_fingerprint TEXT REFERENCES embedding_profiles(fingerprint)
);

CREATE TABLE vector_backend_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    backend TEXT NOT NULL,
    backend_schema_version INTEGER NOT NULL,
    indexed_profile_fingerprint TEXT REFERENCES embedding_profiles(fingerprint),
    build_status TEXT NOT NULL,
    built_at TEXT
);
```

`embedding_profiles`はembeddingの意味と生成契約だけを表し、backend列を持たない。
`active_embedding_state`はuser configから選ばれたprofileの派生写し、
`vector_backend_state`は同じembedding profileをどのbackend/schemaでindex化したかを表す。
ExactScanからsqlite-vecへ切り替えてもprofile fingerprintと既存embeddingの意味は変わらず、
vector indexだけを再構築する。SQLite内stateとuser configが食い違う場合はuser configを正として
stale扱いにし、暗黙にSQLiteの値をconfigへ書き戻さない。

Python validationとDB CHECKの両方で、immutable `model_revision`または明示的な
`profile_epoch`の最低1つを要求する。test fakeも固定`profile_epoch`を明示し、例外扱いしない。

sqlite-vec tableはdimensionをDDLへ埋める必要があるため、active profile変更時に
`memory_vector_index`をdrop/recreateする。正確な`vec0` DDLとtext primary key対応は
採用versionをpinしたWindows spike後に確定する。SQL文字列生成はdimensionを整数検証し、
任意文字列をidentifierへ展開しない。

canonical BLOB encoding/decodingは単一moduleへ集約し、little-endian IEEE 754 float32、
正確に`dimension * 4` bytes、全要素finiteを必須とする。vectorはcosine用にL2 normalizeを標準とする。dimension×4 bytes/Memoryに加え
index overheadを容量見積りへ使う。SQLite DB全体が消えてもMarkdownから再生成できる。

## 6. Invalidationとmigration

embedding cacheが有効なのは次がすべて一致するときだけ。

1. `memory_id`
2. active `profile_fingerprint`
3. 現在のcanonical document `content_hash`

vector indexが有効なのは、さらにuser configのbackend、backend schema version、
`indexed_profile_fingerprint`、`build_status='ready'`が一致するときだけである。

| 変化 | 動作 |
|---|---|
| title/content変更 | hash不一致のMemoryだけstale。再生成までvector channelから除外 |
| model/revision/profile_epoch/contract変更 | 新fingerprint。旧行を検索に使わず、新profileをbatch生成 |
| dimension/normalization/template変更 | 新fingerprint。vector tableをstaging再構築 |
| Memory inactive/archive | vectorは残っても検索時に`memories.status='active'`で除外。cleanup可能 |
| Memory削除 | FK cascade + backend delete |
| vector cache破損/欠落 | lexicalは継続。`embeddings rebuild`で再生成 |

既存DBは`CREATE TABLE IF NOT EXISTS`で非破壊追加する。既存Memory Markdownは変更しない。
legacy DBにはactive profileがないため、user configがなければVector機能をdisabledとみなし、
起動時にmodel downloadや全件embeddingを暗黙実行しない。user configがあればSQLite stateを
そこから派生構築する。profile切替はstaging profile/indexを完成させてから
短いtransactionでactive pointerを切替え、途中失敗時は旧profileを維持する。

## 7. APIとmodule構成案

```text
brain_twin/
  embedding_provider.py   # Protocol、profile、typed errors（SDK非依存）
  embedding_config.py     # user config path/read/validation（秘密値は扱わない）
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

canonical embedding cacheの保存・更新・削除はDB repositoryと将来のservice層の責務とする。
`VectorIndexBackend`のmutation APIは派生search indexだけを同期する
`sync_upsert()` / `sync_delete()` / `clear_index()`であり、canonical BLOBを変更しない。
将来のserviceはcanonical cacheを先にtransaction方針に従って変更し、その後backend indexを
同期する。ExactScanは独立indexを持たないため3操作がno-op、SqliteVecBackendではvec0へ反映する。
rebuildはcanonical cacheからbackend indexを再構築し、providerの再実行を要求しない。

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
- Hybrid lexical channelは`search.search()`を呼ばない。DB層のpure BM25候補API
  （新設`db.search_lexical_candidates()`を第一候補。現`db.search()`を流用する場合も
  「metadata未適用」のcontractを明示）からlexical relevance rankを得る。
- vector channelもcosine/distanceだけのpure relevance rankとする。両方をRRFした後に、
  `metadata_multiplier(importance, confidence, recency)`を**1回だけ**適用する。
- 現行`search.search()`はBM25へmetadataを既に適用した後方互換APIなので、Hybrid channelへ
  その順位を渡して再度metadataを掛けることを禁止する。
- 実装では現行metadata式を共通helperへ抽出できるが、その前に固定clockを使った
  characterization testを追加し、既存`search()`の各scoreと最終orderが完全一致することを
  証明する。refactor後も既存APIはpure lexical DB候補 + helperを内部利用して同じ結果を返す。
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

Sprint 4B実装では`EmbeddingService`がこのflowを担当する。DB本文読込はmemory_id keyset、
provider/DB read/commit batchは独立した中央policy、retryは`EmbeddingTransientError`だけを対象に
bounded exponential backoffとする。各成功commit chunkはcanonical保存→backend `sync_upsert`→
commitの順で確定する。不正output batchは保存せず、途中失敗時の確定済みbatchはresumeでskipする。
新profileのpartial cacheは残す一方、active pointer/backend ready stateは全件+build成功後のみ更新する。

hardening後のbackend同期invariant: targetが現在active profileで、backend id/schema/indexed profileが
一致し`ready`の場合だけincremental `sync_upsert`する。targetがstaging profile、または同profileでも
backend stateがreadyでない場合、生成中はcanonical cacheだけを保存してactive indexへ触れない。
全canonical rowがreadyになってから`build(target)`し、成功後だけprofile/backend stateを切り替える。
途中失敗時は旧active index/stateを維持し、partial target cacheだけをresume用に残す。

stale embeddingは検索不能というinvariantを持つ。Memory title/contentのSQLite更新triggerが全profileの
該当cache rowを`is_valid=0`へ即時invalid化し、成功したcanonical upsertだけが1へ戻す。
metadata-only変更ではinvalid化しない。Backend searchは本文/hashを再計算せず、このrepository validityを
scoring/top-K選抜前に適用しなければならない。ExactScanはvalid rowだけをSQL取得する。
validity列導入前のlegacy cacheはmigration時に保守的な0とし、次回syncでのみ再valid化する。

### query

1. lexical channelとquery embedding/vector channelを実行。
2. active Memoryだけを候補にする。
3. RRF + metadataでPrimaryを作る。
4. requested limitだけ詳細/Entityを取得。
5. `--related`なら既存1-hop expansionへ渡す。

query embeddingは短TTLのprocess内LRUを任意採用できるが、query本文を永続DBへ保存しない。

### SQLite/vector cache全削除からの完全復旧

1. OS user config領域（または`BRAIN_TWIN_CONFIG`）から非秘密Embedding構成を読む。
2. config schemaを検証する。immutable revisionまたはprofile_epoch、dimension、backend等が
   不足/不正なら、MarkdownやSQLiteを書き換えず明確に停止する。
3. credentialは環境変数/OS credential store等から別途解決する。user configへsecretは書かない。
4. VaultのMarkdownから既存reindexでMemory metadata/FTS/entities/linksを再構築する。
5. configからEmbeddingProfileとfingerprintを再作成し、SQLite profile/stateの派生写しを作る。
6. canonical embedding document/hashをMarkdown由来Memoryからbatch生成する。
7. Embedding Providerでstale/missing全件を再embeddingし、派生cacheへ保存する。
8. configで選択したVectorIndexBackendのstaging indexを全件から再構築する。
9. 件数、dimension、profile fingerprintを検証後、active profile/backend stateをreadyへ切り替える。
10. Hybrid/Vector searchを有効化する。途中失敗時もMarkdownとuser configは不変で、lexical searchは使える。

したがって、SQLiteはuserが選んだ構成を決める場所ではない。SQLite全削除後も、user configと
Markdownの2つからembedding/vectorを同じ契約で再生成できる。

## 10. Reindex flow

既存`python brain.py reindex`がprovider/network不調で失敗する後方非互換を避ける。

1. `reindex`は従来どおりMarkdownからmetadata/FTS/entities/linksを完全再構築。
2. vector cacheは失われても正常。active profile/backendはSQLiteからではなくuser configから復元する。
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
- revision非公開providerでprofile_epoch変更により全再生成し、`unknown`単独を拒否する。
- SQLite全削除後、user config + Markdownだけで同じprofile/backendを再構築する。
- legacy DBの非破壊migration、cache全削除から再生成。
- inactive/deleted Memory除外、profile切替途中のrollback。

### backend contract

- sqlite-vecとexact backendで同じ既知vectorのtop K/order。
- insert/update/delete、dimension、empty index、large ID batch。
- Windows CI/spikeでextension load/unloadと対応SQLite versionを確認。

### ranking/retrieval

- lexical-only、vector-only、両方hit、重複dedupe、決定的tie。
- pure BM25 rankとpure vector rankをRRFし、metadata helperの呼出しが候補ごとに1回だけ。
- Hybridが`search.search()`ではなくpure DB lexical candidate APIを使うcontract test。
- metadata helper抽出前後で既存`search()`のscore/orderが完全一致するcharacterization test。
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
- providerがimmutable revisionを公開しない場合、user configのprofile_epoch更新を必須の
  世代切替手段とし、`unknown`のまま継続しない。
- 日本語/英語混在の実データ評価後にmodelを選ぶ。特定model名を設計段階で固定しない。

## 14. Sprint分割案

### Sprint 4A — contracts and Windows storage spike

- provider/backend Protocol、fake provider、canonical document/hash。
- OS user config Source of Truth、generation key validation、SQLite全削除復旧flow。
- schema migration案をtest DBで実証。
- sqlite-vecのWindows install/load/CRUD/KNN/rebuild benchmark。
- Gate: sqlite-vec採用確定、またはExactScanを初期backendに切替。

実測結果は`docs/SQLITE_VEC_WINDOWS_SPIKE.md`を参照。2026-08-25のWindows AMD64環境で
sqlite-vec 0.1.9はPASSしたため、SqliteVecBackendをSprint 4B以降の候補とする。
0.1.9ではvec0の更新は`UPDATE`ではなくdelete+insertをadapter内のupsert primitiveにする。
core dependency化と本番adapter実装はこの判定には含めない。

### Sprint 4B — rebuildable embedding cache

- DB repository、sync/rebuild、invalidation、resume、CLI管理command。
- local deterministic fakeでreindex完全復元を先に保証。
- production providerはまだ1種類に限定し、LLM interfaceは作らない。

hardening完了、外部レビューGO受領(2026-08-25)。production providerとSqliteVecBackendは
意図的に未実装のまま。管理CLIは独立した`embeddings status/sync/rebuild`を採用し、通常
`reindex`とは接続しない。GOと同時に見つかった、providerの問い合わせ中にMemoryが変更される
とstale vectorがvalidとして保存されうるraceは、Sprint 4Cの一部として修正した。最初の修正
(書き込み直前のshort transactionでのcontent_hash再確認)は「providerの問い合わせ中」の
変更は検出できたが、「再確認の読み込み」と「実際の書き込み」の間にもごく短い窓が残って
いたため、Sprint 4C final hardeningでこの再確認の読み込み自体を`BEGIN IMMEDIATE`で
取得した書き込みlockの内側で行うように変更し、read-verify-writeを1つのtransaction境界に
した(providerの問い合わせ自体はtransaction外のまま)。staging activate直前の
`ready == total_active`再確認は維持している。

### Sprint 4C — vector and hybrid primary retrieval

architecture(pure lexical channel、Vector availability gate、Weighted RRF、metadata
multiplierの単一適用、lazy detail fetch、CLI opt-in、handoff protocol)はレビューで承認
済み。embedding consistency raceの完全な原子化とHybrid lexical candidateの決定的
tie-break(`ORDER BY score ASC, m.id ASC`、`db.search()`/`search.search()`は不変)を
final hardeningとして実施(2026-08-25)。外部レビュー待ち。

- `vector_search()`(availability gate + query embedding検証 + 本文遅延取得)、
  weighted RRF `hybrid_search()`、`RetrievalWeights`による中央weights。
- Hybridのlexical channelは`search.search()`を呼ばず、新設のpure BM25候補API
  (`db.search_lexical_candidates()`)を使う。metadata multiplierの式は
  `retrieval_weights.py`へ集約し、既存`search()`の出力はcharacterization testで固定した
  まま変わっていない。
- CLI opt-in(`search --vector` / `search --hybrid`、mutually exclusive)とdiagnostic
  component scores(`--verbose`)。capability unavailable時は明確なerrorで拒否する
  (黙ってlexicalへfallbackしない)。
- Associative Retrieval(`--related`)との統合はまだ行っていない(Sprint 4D予定)。
  `--vector --related` / `--hybrid --related`は明確な未対応errorになる。

### Sprint 4D — associative integration and hardening

- hybrid Primaryを既存1-hop expansionへ接続。
- 10k以上のWindows benchmark、failure/recovery/migration test。
- 設計値を評価結果で調整し、Vector Search完了レビューへ提出。

## 15. 未解決事項（設計レビューで決める）

1. Windows spikeでpinするPython/sqlite-vec/SQLite version。
2. 初期production embedding providerと日本語評価dataset/query。
3. 初期modelのdimension、license、immutable revision/profile_epoch運用、download容量。
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
