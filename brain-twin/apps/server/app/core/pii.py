"""packages/rules/pii_detection.v1.json を使ったルールベースの機密情報らしさ検出。
仕様書 3-11 の通り、検出しても本文は一切改変しない。検出結果は
「ログに原文を出さない」等の下地としてのみ使う(pipeline.py参照)。"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from app.core.paths import packages_dir


def _rules_path() -> Path:
    return Path(packages_dir()) / "rules" / "pii_detection.v1.json"


@lru_cache(maxsize=1)
def _compiled_rules() -> list[tuple[str, re.Pattern[str]]]:
    path = _rules_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for rule in data.get("rules", []):
        flags = re.IGNORECASE if "i" in rule.get("flags", "") else 0
        compiled.append((rule["id"], re.compile(rule["pattern"], flags)))
    return compiled


def has_sensitive_content(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for _rule_id, pattern in _compiled_rules())


def matched_rule_ids(text: str) -> list[str]:
    """将来のエクスポート/ログ出力時のフラグ付けに使う想定。どのルールが反応したかを返す。"""
    if not text:
        return []
    return [rule_id for rule_id, pattern in _compiled_rules() if pattern.search(text)]
