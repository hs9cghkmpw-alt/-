# thought_split v1

- 初版。
- テンプレート変数: `{{json_schema}}` (thought_split.schema.jsonをJSON文字列化したもの), `{{capture_text}}`, `{{captured_at}}`
- 対応スキーマ: `packages/shared-types/src/thought_split.schema.json`
- 想定モデル: Qwen2.5 instruct系 (7B目安。軽量端末では3Bも可、ただしJSON整形の安定性は下がる)
- 既知の傾向: 稀に配列を1要素だけ返し分割が甘くなることがある。`analysis_version` = `v1` として記録し、
  将来 `v2` でfew-shot例を追加する余地を残す。
