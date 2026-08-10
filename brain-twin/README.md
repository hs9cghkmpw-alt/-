# Brain Twin — 疲れない第二の脳

> 私は疲れる。でも、もう一つの脳は疲れない。

Brain Twin は、頭に浮かんだことを **整理せず、分類せず、文章として整えず、そのまま預けられる「第二の脳」** です。
一般的なToDoアプリでもメモアプリでもありません。預けられた内容は裏側で保存・分割・整理・関連付けされ、
必要なときだけ呼び戻されます。あなたに管理作業をさせないことが、最も大事な設計思想です。

- iPhoneのホーム画面から使うPWA(Safariで動作)
- データはすべて **あなたのPC内**(SQLite)に保存
- AI処理はすべて **あなたのPCのOllama**(ローカルLLM)で実行。外部AI APIは一切使いません
- iPhoneとPCは **Tailscale** で接続。一般のインターネットには公開されません

---

## 初めて使う方へ

PCやプログラミングに詳しくない方は、まず以下を読んでください。セットアップから
毎日の使い方、トラブル時の対処までを、専門用語をかみ砕きながら順番に説明しています。

**→ [Brain Twin 完全説明書](docs/COMPLETE_GUIDE_JA.md)**

---

## 1. 必要なもの

| 項目 | 必要なもの |
|---|---|
| サーバーになるPC | 常時起動できるWindows/macOS/Linux PC |
| コンテナ実行環境 | Docker Desktop (Windows/macOS) または Docker Engine + Compose (Linux) |
| ローカルAI | [Ollama](https://ollama.com)(PCに直接インストール、またはDocker内で実行) |
| ネットワーク | [Tailscale](https://tailscale.com) アカウント(無料枠で可)、PCとiPhoneの双方にインストール |
| クライアント | iPhone (Safari) |

## 2. 最短起動手順

```bash
git clone <このリポジトリ> brain-twin
cd brain-twin

# macOS / Linux
./scripts/setup.sh

# Windows (PowerShell)
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
# .\scripts\setup.ps1
```

`setup.sh` / `setup.ps1` は以下を自動で行います:

1. `.env` を `.env.example` からコピー(なければ)
2. `data/` ディレクトリの準備
3. Ollamaの有無を確認(なければ案内を表示)
4. `docker compose build && docker compose up -d`
5. `alembic upgrade head` でDBスキーマを最新化
6. ヘルスチェック
7. iPhoneとペアリングするための次の手順を表示

手動で行う場合は以下と同義です:

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose exec server alembic upgrade head
curl http://127.0.0.1:8080/api/health   # Web(Nginx)経由。/api はserverへ内部転送される
```

Windows特有の手順は [SETUP_WINDOWS.md](./docs/SETUP_WINDOWS.md) を参照してください。

## 3. Ollamaモデルの導入

初期候補は日本語性能と軽さのバランスを考慮した **Qwen2.5 instruct系** です。
意味検索用の埋め込みモデルは、生成モデルとは別に **bge-m3**(多言語対応)を使います。

```bash
# ホスト側にOllamaをインストール済みの場合(デフォルト構成)
ollama pull qwen2.5:7b-instruct
ollama pull bge-m3

# Docker内でOllamaも動かす場合
docker compose --profile dockerized-ollama up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b-instruct
docker compose exec ollama ollama pull bge-m3
```

PCのスペックに応じて `.env` の `OLLAMA_MODEL` を `qwen2.5:3b-instruct`(軽量)や
`qwen2.5:14b-instruct`(高精度)に変更できます。詳細は [OLLAMA_SETUP.md](./docs/OLLAMA_SETUP.md)。

**モデルが未導入でもアプリ自体は起動・入力・保存・検索が可能です**(AI整理だけが後回しになります)。

## 4. Tailscale接続

PCとiPhoneの両方に Tailscale をインストールし、同じTailscaleアカウントでログインしてください。
一般公開(ポート開放・Tailscale Funnel)は行いません。

Webサービスを同一オリジンで公開します(`/api`はNginxがserverへ内部転送するため、
公開すべきポートは1つだけです):

```bash
sudo tailscale serve --bg 8080
```

詳細手順・コマンドの検証内容は [TAILSCALE_SETUP.md](./docs/TAILSCALE_SETUP.md)。

## 5. iPhoneから開く・ホーム画面へ追加

1. iPhoneのSafariで、`tailscale serve`実行時に表示されたURL
   (例: `https://your-pc.tailnet-name.ts.net`)を開く
2. 共有ボタン → 「ホーム画面に追加」
3. ホーム画面のアイコンから起動(standalone表示になります)

詳しくは [SETUP_IPHONE.md](./docs/SETUP_IPHONE.md)。

## 6. 初回ペアリング

PC側でペアリングコードを発行します(このコマンドはPC上でのみ実行できます。
Web経由の公開エンドポイントにはこの機能は存在しません):

```bash
docker compose exec server curl -s -X POST http://localhost:8000/api/pairing/start
```

表示された `code` を、iPhoneのBrain Twin初回起動時の画面(サーバーアドレスの入力は
不要で、コードの入力のみです)で入力してください。

## 7. バックアップ

```bash
./scripts/backup.sh          # macOS/Linux (手動実行)
# .\scripts\backup.ps1       # Windows (手動実行)
```

毎日自動実行するには:

```bash
./scripts/install_backup_cron.sh        # macOS/Linux
# .\scripts\install_backup_task.ps1     # Windows
```

最低7世代を自動的に保持し、実行ログは `data/backups/backup.log` に残ります。
詳細は [BACKUP_RESTORE.md](./docs/BACKUP_RESTORE.md)。

## 8. 復元

```bash
./scripts/restore.sh --list          # 一覧表示
./scripts/restore.sh --latest        # 最新から復元
./scripts/restore.sh --file <名前>    # 特定世代から復元
```

復元前に現在のDBは自動的に安全コピーされます。詳細は [BACKUP_RESTORE.md](./docs/BACKUP_RESTORE.md)。

## 9. アップデート

```bash
git pull
docker compose build
docker compose up -d
docker compose exec server alembic upgrade head
```

## 10. 停止

```bash
docker compose down       # コンテナを停止(データは data/ に残る)
docker compose down -v    # + Docker内Ollamaのモデルボリュームも削除する場合(通常は不要)
```

## 10.4. Dockerの基本操作コマンド

UAT(受け入れ試験)や日々の運用でよく使う、Docker Composeの基本4コマンドです。

```bash
docker compose up -d      # 起動する(バックグラウンドで動き続ける)
docker compose ps         # 各コンテナ(server/web)の状態を確認する
docker compose logs       # 全コンテナのログを表示する(-f で追従表示)
docker compose down       # 停止する(データは data/ に残る)
```

| コマンド | 何をするか | 正常時の表示 |
|---|---|---|
| `docker compose up -d` | server/webコンテナを起動する | エラーなく完了し、プロンプトに戻る |
| `docker compose ps` | 起動中のコンテナ一覧を表示する | `server`/`web`の`STATUS`が`Up`または`running` |
| `docker compose logs` | 各コンテナの出力ログを表示する(`logs -f server`のように対象を絞れる) | エラーが無く、リクエストを処理しているログが流れる |
| `docker compose down` | コンテナを停止・削除する(データ自体は`data/`に残るため消えない) | エラーなく完了する |

## 10.6. 開発時の起動高速化

本番用の起動(`docker compose up -d`)は、毎回`npm install`・`vite build`を
含むイメージビルドが走るため数分かかる。開発中にコードを頻繁に変更する場合は、
代わりに開発用の独立したcompose定義を使うと、2回目以降は数秒〜十数秒で
起動できる(ソースの変更はボリュームマウント経由でそのまま反映され、
vite HMR・`uvicorn --reload`が効く)。

```bash
docker compose -f docker-compose.dev.yml up
```

- 本番用の`data/`とは別の`data-dev/`を使うため、本番データには一切触れない。
- 初回のみ`npm install`/`pip install`に時間がかかる。
- 本番用`docker-compose.yml`・`docker compose up -d`には一切影響しない。

## 10.5. まとめて検証する

個別の手順を手作業でつなげなくても、可能な範囲を1コマンドでまとめて検証できます。

```bash
./scripts/verify_all.sh          # macOS/Linux
# .\scripts\verify_all.ps1       # Windows
```

構文チェック・Python単体テスト・pytest・フロントエンド単体テスト/ビルド・Dockerビルド・
Docker統合テスト・Playwright E2E・バックアップ/復元を順に実行し、最後に一覧で結果を
表示します(1つが失敗しても残りは実行し続けます)。重い段階を飛ばしたい場合:

```bash
./scripts/verify_all.sh --skip-docker --skip-e2e
```

**Ollama・Tailscale・iPhone実機の確認だけは、この一括検証の対象外です**(性質上、
自動化できないため)。スクリプトの最後に、それぞれ何を確認すればよいかが案内されます。

### 実機での最終検証(Windows)

`verify_all.ps1`より踏み込んだ、実機での最終確認を1コマンド・1ログファイルで
完結させたい場合:

```powershell
.\scripts\BrainTwin-Final-Verification.ps1
```

新品展開 → `docker compose build --no-cache` → 起動 → health → backend pytest →
cron → frontend build/typecheck/unit test → runtime smoke test → pairing まで
一括実行し、結果を`BrainTwin-Final-Verification.log`1個にまとめます。途中で
失敗した場合も、その1ファイルだけで原因を追えるよう、失敗した段階・コマンド・
終了コード・`docker compose ps`・server/webのログ・トレースバックを自動的に
まとめて記録します。詳細は`docs/FINAL_VERIFICATION.md`を参照してください。

## 11. トラブルシューティング

| 症状 | 確認すること |
|---|---|
| Docker Desktopが起動しない/認識されない | タスクバーのDockerアイコンが動いているか。`docker --version` が通るか。PC再起動後に再試行 |
| iPhoneから繋がらない | Tailscaleが両方の端末で接続中か。`tailscale status` |
| 「PC未接続」のまま | `docker compose ps` でserverが起動しているか、`docker compose logs server` |
| Ollamaが動いていない/モデル未取得 | `docker compose exec server python scripts/ollama_preflight.py` で到達性・モデル有無を確認 |
| AI整理が進まない | `docker compose exec server curl http://host.docker.internal:11434/api/version`(ホストOllama時)。詳細画面(設定→状態)でOllama到達性を確認 |
| ペアリングコードが無効 | 10分で失効します。再度 `/api/pairing/start` を実行してください |
| 入力が消えた気がする | 消えていません。IndexedDBに残っています。同期待ちの件数は設定画面の詳細状態で確認できます |
| ポートが競合している(`bind: address already in use`等) | `.env`の`WEB_PORT`(既定8080)を他のポートに変更し、`docker compose up -d`をやり直す |
| `npm install`が失敗する | Node.jsのバージョン(18以上推奨)を確認。社内プロキシ等の場合は`npm config get registry`も確認。フロントのビルド自体はDocker内で完結するため、ホスト側npmが無くても`docker compose up -d`自体は可能 |

より詳しい構成・UAT向けの詳細な原因/確認方法/修正方法は
[Brain Twin 完全説明書](docs/COMPLETE_GUIDE_JA.md) の「9. トラブルシューティング」、
アーキテクチャは [ARCHITECTURE.md](./docs/ARCHITECTURE.md)、API仕様は
[API.md](./docs/API.md) を参照してください。

## 12. データの保存場所

- データベース: `data/database/brain_twin.sqlite3`(PC上、Dockerボリュームでバインドマウント)
- バックアップ: `data/backups/`
- 書き出し(エクスポート): `data/exports/`

## 13. 外部へ送信されるデータの有無

**ありません。** 思考の本文・分析結果は、あなたのPC内のSQLiteとOllamaの間だけで処理されます。
外部AI API(OpenAI/Gemini/Claude API等)へは一切送信しません。詳細は [PRIVACY.md](./docs/PRIVACY.md)。

## 14. 完全削除方法

- 個別の思考/入力: アプリ内の「忘れてよい」操作(ソフトデリート)、または設定画面から完全削除
- 全データ削除:
  ```bash
  docker compose down
  rm -rf data/database/* data/backups/* data/exports/*
  ```
  (バックアップも消えるため、本当に全消去したい場合のみ実行してください)

---

## プロジェクト構成

```
brain-twin/
├ apps/
│  ├ web/      # React + TypeScript + Vite PWA (フロントエンド)
│  │  └ e2e/   # Playwright E2Eテスト
│  └ server/   # FastAPI + SQLAlchemy + Alembic (バックエンド)
├ packages/
│  ├ shared-types/  # フロント/バック共通の型・JSON Schema
│  ├ prompts/       # Ollamaへのプロンプト(バージョン管理)
│  └ rules/         # 機密情報検出等のルールセット
├ testing/
│  └ fake_ollama/   # E2E・統合テスト用のOllamaスタブ(標準ライブラリのみ)
├ data/        # SQLite DB・バックアップ・エクスポート(Gitには含めない)
├ data-test/   # 統合テスト専用のデータ(本番data/とは完全分離、Gitには含めない)
├ scripts/     # セットアップ・バックアップ・復元・検証スクリプト
├ docs/        # 詳細ドキュメント(このファイル以外)
├ verification/ # 開発時の動作検証スクリプト(VERIFICATION.md参照)
├ docker-compose.yml       # 本番用
└ docker-compose.test.yml  # 統合テスト専用(本番と完全分離)
```

## ドキュメント一覧

- [ARCHITECTURE.md](./docs/ARCHITECTURE.md) — システム構成
- [API.md](./docs/API.md) — API仕様
- [DATA_MODEL.md](./docs/DATA_MODEL.md) — データモデル
- [AI_PIPELINE.md](./docs/AI_PIPELINE.md) — AI処理パイプライン
- [SECURITY.md](./docs/SECURITY.md) — セキュリティ設計
- [PRIVACY.md](./docs/PRIVACY.md) — プライバシー方針
- [BACKUP_RESTORE.md](./docs/BACKUP_RESTORE.md) — バックアップ・復元
- [SETUP_WINDOWS.md](./docs/SETUP_WINDOWS.md) / [SETUP_IPHONE.md](./docs/SETUP_IPHONE.md) / [TAILSCALE_SETUP.md](./docs/TAILSCALE_SETUP.md) / [OLLAMA_SETUP.md](./docs/OLLAMA_SETUP.md) — 個別セットアップ手順
- [VERIFICATION.md](./VERIFICATION.md) — 実施したテスト・検証の記録と既知の制限

## ライセンス・利用について

このリポジトリは個人の私的利用を前提とした構成です。App Storeでの配布やネイティブアプリ化、
複数ユーザーでの共有機能はMVPの対象外です(詳細は各ドキュメント参照)。
