# Brain Twin 2.0 — Phase 1: Memory Foundation

> スマホでは思ったことを呟くだけ。PC側で自動整理し、Obsidianに長期記憶として保存し、
> 必要なときにAIが検索・連想・比較して思い出せる第二の脳。

Brain Twinの本体はAIそのものではなく、**永続的な記憶基盤**です。AIモデルは将来交換可能にします。
このディレクトリは「Claude Code向け実装指示書」の **Phase 1(Memory Foundation)** を実装したものです。

- LLM APIは使いません(Phase 1はダミー分類で十分という指示書の方針通り)。
- Dockerは不要です。Python + Markdown + SQLite + Obsidian のみで動きます。
- **Markdown(Obsidian Vault)が正本、SQLiteは検索用のindex/cache**です。SQLiteが壊れても
  `python brain.py reindex` でVaultから作り直せます。

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

## 使い方

```bash
python brain.py add "今日はBrain Twinの設計について考えた"
python brain.py process
python brain.py search "Brain Twin"
```

- `add` — 思ったことをそのまま記録するだけ。整理はしない(指示書2章「ユーザーに整理させない」)。
- `process` — 未処理の入力をDaily Logへ保存し、Long-term Memoryに昇格させるかをPhase 1のダミー
  分類器(`brain_twin/classify.py`、キーワードベース)で判定する。雑談は消さずDaily Logに残す。
- `search` — Long-term Memoryをキーワード検索する(FTS5 + importance/confidence/recencyの
  簡易Hybrid Retrieval)。
- `reindex` — SQLite indexが壊れた/消えた場合に、Vault(Markdown)から作り直す。

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
│  ├ raw_log_io.py        # Layer 1(Raw Log) / Layer 2(Daily Log)
│  ├ memory_io.py         # Layer 3(Long-term Memory)
│  ├ db.py                # SQLite index (FTS5 trigram)
│  ├ pipeline.py          # add / process / reindex の実処理
│  ├ search.py            # 簡易Hybrid Retrieval
│  └ cli.py               # argparseによるコマンド定義
├ tests/                  # pytest (25 tests)
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
- **ID生成はSQLiteに依存させず、Vault上の既存ファイルをスキャンして決めている**
  (`brain_twin/ids.py`)。指示書25章「SQLiteが壊れてもMarkdownから再構築可能にする」を
  ID生成の場面でも徹底するため。
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
- **Entity抽出・Link生成はPhase 1では実装していない**。指示書28章のPhase分割で
  Entity Extraction / Link生成は明示的にPhase 2の項目とされているため、Phase 1では
  スキーマ(`entities` / `links` フィールド、`entities` / `links` テーブル)だけ用意し、
  値は空のままにしている。
- **検索対象はLong-term Memoryのみ**とし、Daily Log(雑談を含む生ログ)は検索対象に
  含めていない。指示書15章のHybrid Retrievalの説明がMemoryを主語にしていることに合わせた。
- **`ask`(自然言語での質問応答)はPhase 1では未実装**。指示書28章でPhase 4「AI Brain」に
  明示的に分類されており、LLM接続が前提のため。指示書35章のPhase 1必須項目にも含まれていない。

## 実施した検証

- `pytest tests/` — 25件、すべてPASS(ID生成、frontmatterの往復、分類器のキーワード判定、
  add→process→search→reindexの一連の流れ、雑談がMemoryに昇格しないこと、処理の冪等性、
  SQLite全消去後にVaultから完全に再構築できること、を含む)。
- 指示書37章の完成条件(`add` → `process` → `search`)をそのまま実行し、期待通りの
  出力になることを確認済み。
- **Docker実機検証はしていません**(このプロジェクトはPhase 1時点でDockerを使わない設計)。
- 実際のObsidianアプリでVaultを開いての目視確認は**未実施**です(このセッションの環境に
  Obsidianが無いため)。プレーンなMarkdown + frontmatilterとしての妥当性はテストで確認済みですが、
  Obsidian特有のレンダリング(wikilink `[[...]]` の解決等、Phase 1では `links` は空配列のため
  未使用)は実機での確認をお願いします。

## 今後(このPhase 1には含まれない)

指示書のPhase 2以降: 自動ラベリングの高度化・Entity抽出・Link生成・Contradiction Detection・
Memory Consolidation・Vector Search・LLM Provider Interface・スマホ連携・`ask`コマンド、など。
