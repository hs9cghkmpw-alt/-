"""Markdownファイルの YAML frontmatter (`---` で挟まれた先頭ブロック) の読み書き。

Obsidianの標準的なfrontmatter形式に合わせる。日本語を含むため、
書き込み時は allow_unicode=True / 引用符でエスケープしないようにする。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

_DELIMITER = "---"


@dataclass
class ParsedMarkdown:
    frontmatter: dict[str, Any]
    body: str


def dump(frontmatter: dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip("\n")
    return f"{_DELIMITER}\n{yaml_text}\n{_DELIMITER}\n\n{body.strip()}\n"


def parse(text: str) -> ParsedMarkdown:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _DELIMITER:
        return ParsedMarkdown(frontmatter={}, body=text.strip() + "\n")

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _DELIMITER:
            end_idx = i
            break
    if end_idx is None:
        return ParsedMarkdown(frontmatter={}, body=text.strip() + "\n")

    yaml_block = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :]).strip() + "\n"
    data = yaml.safe_load(yaml_block) or {}
    if not isinstance(data, dict):
        data = {}
    return ParsedMarkdown(frontmatter=data, body=body)
