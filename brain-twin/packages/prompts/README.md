# packages/prompts

Ollama へ渡すプロンプトは `apps/server` のコードへ直書きせず、ここでバージョン管理する。

## 方針

- 1機能 = 1ディレクトリ。例: `thought_split/`
- 1バージョン = 1サブディレクトリ (`v1/`, `v2/`, ...)。**過去バージョンは削除しない。**
  `thoughts.ai_prompt_version` に記録されたバージョンで、後から同じプロンプトを再現できることが目的。
- 各バージョンには最低限 `system_prompt.txt` を置く。テンプレート変数は `{{variable}}` 表記。
- プロンプトの意味が変わる変更は必ず新バージョンを切る (既存ファイルの上書き禁止)。
- モデルを変更しただけ (プロンプトは同じ) の場合は `thoughts.ai_model` 側の値だけが変わる。

## 現在のバージョン

| 機能 | 最新版 | 用途 |
|---|---|---|
| thought_split | v1 | 1つのcaptureを複数のthoughtへ分割し、属性を推定する (仕様書 7.2/7.3) |

## 再解析について

モデルやプロンプトを変更した場合、過去の `thoughts` は自動的には再生成されない。
`POST /api/processing/{capture_id}/retry` で対象の capture を指定して再解析すると、
新しい `ai_model` / `ai_prompt_version` / `analysis_version` で新しい `thoughts` 行が作られ、
古い行は `deleted_at` が設定される (物理削除はしない)。
