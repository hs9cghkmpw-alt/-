#!/usr/bin/env python3
"""Ollamaの疎通・モデル導入状況を診断する(setup.sh・README『11. トラブルシューティング』参照)。
情報提供のみが目的で、失敗してもセットアップ自体は止めない(仕様書13: モデル未導入でも
アプリは起動・入力・保存・検索が可能)。呼び出し側は `|| true` で終了コードを握りつぶす想定。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.ollama_client import OllamaClient, OllamaUnavailableError  # noqa: E402
from app.config import get_settings  # noqa: E402


async def main() -> int:
    settings = get_settings()
    client = OllamaClient()

    print(f"Ollama接続先: {settings.ollama_base_url}")
    healthy = await client.check_health()
    if not healthy:
        print("[NG] Ollamaに接続できません。起動しているか確認してください。")
        return 1
    print("[OK] Ollamaに接続できました。")

    try:
        models = await client.list_models()
    except OllamaUnavailableError as e:
        print(f"[NG] モデル一覧の取得に失敗しました: {e}")
        return 1

    all_ok = True
    for label, target in (
        ("生成モデル", settings.ollama_model),
        ("埋め込みモデル", settings.ollama_embedding_model),
    ):
        prefix = target.split(":")[0]
        found = any(m == target or m.startswith(f"{prefix}:") for m in models)
        if found:
            print(f"[OK] {label} '{target}' は導入済みです。")
        else:
            print(f"[NG] {label} '{target}' が見つかりません。`ollama pull {target}` を実行してください。")
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
