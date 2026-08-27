# AGENTS.md — AI collaboration contract

## Source of Truth

- GitHubのdefault branch、仕様、Issue、PR、commit、CIを共有状態の正本とする。
- 作業開始前に最新の関連Issue/PR、仕様、agent instructions、branch/HEAD/diffを確認する。
- チャット履歴だけを根拠に実装を開始しない。
- 実施していないtest、CI、実機確認をPASSと書かない。
- secret、token、credential、個人情報をcommitしない。

## Maintainability / Git safety

- スパゲッティコードを避け、小さな責務、明示的なinterface、重複しないbusiness logicを優先する。
- default branchへ未レビュー変更を直接commitしない。focused feature branch + draft PRを基本とする。
- 無関係な既存変更を編集・破棄・commitしない。
- merge、PR承認、Issue close、破壊的操作は明示的な人間の許可なしに行わない。

## Context / Token Safety — mandatory

全Agent（ChatGPT、Claude Code、Codexその他）は作業中、残りcontext/token余力と残作業量を継続的に確認または保守的に推定する。正確な残量を取得できない場合でも、この規則は免除されない。

context切れ、出力打切り、作業途中の情報喪失が起きる可能性が高まるまで作業を続けることを禁止する。危険域に入る前に安全なcheckpointを作り、可能な範囲で現在の変更を正しいfeature branchへ保存し、Issue/PRなどSource of Truthへ `AI-HANDOFF` を残して交代する。

`AI-HANDOFF` には必ず以下を含める。
1. 現在の目的
2. 完了済み
3. 未完了
4. branch / commit / PR / Issue
5. 変更ファイル
6. 実行済みtests / CI / 実機結果
7. 既知の失敗・blocker
8. 次に最初に行う具体的な1〜3手
9. 触ってはいけない箇所・安全境界
10. 推測・未検証事項

HANDOFF後に新しい大規模作業を開始しない。次Agentまたは次sessionは最新HANDOFFを最初に読み、重複作業を避けて続きから再開する。トークンを限界まで使うことより、早めで完全な申し送りを優先する。

## AI team handoff

- ChatGPT: PM、設計、仕様分解、統括レビュー。
- Claude Code: 主実装・広いcodebase変更。
- Codex: 独立レビュー、明確な小〜中規模修正、CI確認。
- Human: 実機検証、秘密情報の設定、最終Product判断。
- GitHub Issue/PRをAI間の共有キューとし、人間に長文の手動コピペを要求しない。
