# verification/frontend_sandbox_check/

**これは Brain Twin の公式テストスイートではない。**

公式のフロントエンド単体テストは `apps/web/tests/*.test.ts` であり、
`npm ci && npm run test`(Vitest)で第三者環境でも再現可能な形になっている
(監査修正7対応)。

このディレクトリは、開発時にネットワーク遮断・`npm install`不可のサンドボックス
環境で、`apps/web/src/` 配下のロジックが正しく動作するかを、Node.js標準の
`node:test` + `assert`(Vitestとは別の仕組み)を使って**開発者自身が**
検証するための補助スクリプトである。

- 対象ロジック自体(`src/sync/queueLogic.ts` 等)は公式テストと共通。
- テストの「書き方(アサーション文法)」だけが異なる。
- `tsx`(このサンドボックスにグローバル導入されていたツール)で実行しており、
  **これ自体は第三者が `npm ci` しただけでは再現できない**
  (`apps/web/package.json` の `devDependencies` に `tsx` を追加したのは、
  このスクリプトを将来正式に使う場合の再現性確保のためであり、
  現時点の「公式テスト」は引き続きVitestである)。

実行結果と位置づけの詳細は `VERIFICATION.md` を参照。
