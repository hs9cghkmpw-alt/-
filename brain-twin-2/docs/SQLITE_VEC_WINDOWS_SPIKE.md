# sqlite-vec Windows Compatibility Spike

Date: 2026-08-25

Result: **PASS**

Scope: Sprint 4A技術検証のみ。本番backend実装・core dependency追加ではない。

## Environment

| Item | Result |
|---|---|
| OS | Windows 11 `10.0.22621` |
| Architecture | AMD64, 64-bit Python process |
| Python | 3.12.10 |
| `sqlite3.sqlite_version` | 3.49.1 |
| sqlite-vec package | 0.1.9 (`sqlite-vec==0.1.9` pin candidate) |
| sqlite-vec runtime | `v0.1.9` (`vec_version()`) |

## Safe extension loading

PyPIの`sqlite-vec==0.1.9` Windows AMD64 wheelをproject venvへspike用途でのみ導入した。
任意DLL pathは使わず、installed packageの`sqlite_vec.loadable_path()`が返したpackage内pathを
resolveし、package directory配下であることを確認してから`sqlite_vec.load(conn)`した。
load前だけ`enable_load_extension(True)`、load直後に`enable_load_extension(False)`へ戻した。

実測extension path:

```text
<project>\.venv\Lib\site-packages\sqlite_vec\vec0
```

machine固有の絶対pathは設定・DB・アプリケーションへ保存しない。

## Verified operations

- import / `vec_version()`
- `vec0` virtual table作成 (`FLOAT[3] distance_metric=cosine`)
- serialized float32 vector insert
- `MATCH` + `k` KNN query
- cosine distance（同一方向 `0.0`、直交 `1.0`）
- update/upsert相当: delete + insert
- delete
- drop/create + canonical vectorからのrebuild相当
- extension loadingの即時disable

再実行可能なprobeは`scripts/sqlite_vec_windows_spike.py`。これはruntimeからimportされず、
sqlite-vecを`requirements.txt`へ追加しない。実行にはspike dependencyを明示導入する。

## Decision

この環境ではPASS。SqliteVecBackendを次Sprint候補とする。ただしsqlite-vecはpre-v1であり、
採用時は`0.1.9`をpinし、Windows CIでload/CRUD/KNNを継続検証する。ExactScanBackendは
fallback/referenceとして残すため、将来sqlite-vecが利用不能でもPhaseを継続できる。

既知の注意点: 0.1.9のvec0は通常の`UPDATE`をサポートしないため、adapterのupsertは
transaction内delete+insertとして実装する。今回その本番adapterは実装していない。
