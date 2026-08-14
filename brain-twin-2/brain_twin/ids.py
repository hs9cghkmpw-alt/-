"""ID生成(`mem_20260814_001` のような形式)。

SQLite(index/cache)ではなくVault(正本)上の既存ファイルをスキャンして
連番を決める。これにより、SQLiteを消して再構築(reindex)しても、
その後に生成される新規IDが過去のIDと衝突しない(指示書25章: DB再構築可能性)。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_ID_RE_TEMPLATE = r"{prefix}_(\d{{8}})_(\d{{3}})"


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def next_sequence(vault_dir: Path, prefix: str, date_str: str) -> int:
    if not vault_dir.exists():
        return 1
    pattern = re.compile(_ID_RE_TEMPLATE.format(prefix=re.escape(prefix)))
    max_seq = 0
    for path in vault_dir.rglob(f"{prefix}_{date_str}_*.md"):
        m = pattern.search(path.stem)
        if m and m.group(1) == date_str:
            max_seq = max(max_seq, int(m.group(2)))
    return max_seq + 1


def new_id(vault_dir: Path, prefix: str, dt: datetime | None = None) -> str:
    dt = dt or datetime.now().astimezone()
    date_str = _date_str(dt)
    seq = next_sequence(vault_dir, prefix, date_str)
    return f"{prefix}_{date_str}_{seq:03d}"
