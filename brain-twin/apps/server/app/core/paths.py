"""依存フリーのパス解決ヘルパー。app.config (pydantic-settings) からも、
テスト用にpydantic無しでも呼べるよう、外部ライブラリに依存しない。"""
from __future__ import annotations

import os
from pathlib import Path

# apps/server/app/core/paths.py -> apps/server/app/core -> apps/server/app -> apps/server -> apps -> brain-twin(リポジトリルート)
_REPO_ROOT = Path(__file__).resolve().parents[4]


def packages_dir() -> str:
    """packages/ (prompts, rules, shared-types) の場所を返す。

    Dockerイメージ内では docker-compose.yml が `PACKAGES_DIR=/packages` を設定し、
    ビルド時に packages/ を /packages へコピーする(apps/server/Dockerfile参照)。
    ローカルでDocker無しに実行する場合は、このリポジトリ内の packages/ を使う。
    """
    env_value = os.environ.get("PACKAGES_DIR")
    if env_value:
        return env_value
    return str(_REPO_ROOT / "packages")
