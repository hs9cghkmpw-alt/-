"""テスト用フィクスチャ。

Config は環境変数ではなく明示的な引数として全関数に渡す設計にしているため、
(過去のセッションで問題になった「app.db.engineがimport時に固定される」ような
グローバル状態は存在しない)ここでは単にtmp_path配下を指すConfigを組み立てるだけで
本番のVault/DBに一切触れずにテストできる。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from brain_twin.config import Config


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        project_root=tmp_path,
        vault_dir=tmp_path / "vault",
        data_dir=tmp_path / "data",
    )
