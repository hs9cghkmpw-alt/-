"""packages/prompts/ からプロンプトを読み込み、テンプレート変数を埋め込む。
標準ライブラリのみに依存する(単体テスト容易性のため)。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.paths import packages_dir

CURRENT_THOUGHT_SPLIT_VERSION = "v1"


def _prompts_dir() -> Path:
    return packages_dir() / "prompts"


def _schema_path() -> Path:
    return packages_dir() / "shared-types" / "src" / "thought_split.schema.json"


@dataclass(frozen=True)
class LoadedPrompt:
    version: str
    template: str


@lru_cache(maxsize=8)
def load_thought_split_prompt(version: str = CURRENT_THOUGHT_SPLIT_VERSION) -> LoadedPrompt:
    path = _prompts_dir() / "thought_split" / version / "system_prompt.txt"
    if not path.exists():
        raise FileNotFoundError(f"プロンプトファイルが見つかりません: {path}")
    return LoadedPrompt(version=version, template=path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_thought_split_schema() -> dict:
    schema_path = _schema_path()
    if not schema_path.exists():
        raise FileNotFoundError(f"スキーマファイルが見つかりません: {schema_path}")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def render_thought_split_prompt(*, capture_text: str, captured_at_iso: str, version: str = CURRENT_THOUGHT_SPLIT_VERSION) -> tuple[str, str]:
    """
    戻り値: (system_prompt, prompt_version)
    schema自体は本文内に埋め込みつつ、Ollamaへは別途 format パラメータとしても渡す
    (二重に伝えることでモデルの追従性を上げる)。
    """
    loaded = load_thought_split_prompt(version)
    schema = load_thought_split_schema()
    rendered = (
        loaded.template.replace("{{json_schema}}", json.dumps(schema, ensure_ascii=False, indent=2))
        .replace("{{capture_text}}", capture_text)
        .replace("{{captured_at}}", captured_at_iso)
    )
    return rendered, loaded.version
