"""ID生成(`mem_20260814_001` のような形式)。

2種類の生成方式を使い分ける:

- `new_id()`: raw_log用。SQLite(index/cache)ではなくVault(正本)上の既存ファイルを
  スキャンして連番を決める。これにより、SQLiteを消して再構築(reindex)しても、
  その後に生成される新規IDが過去のIDと衝突しない(指示書25章: DB再構築可能性)。
  `add`は常に新しい入力なので、スキャンベースの連番採番で問題ない。
- `derive_memory_id()`: Memory用。raw_log_idから決定的に導出する(スキャンしない)。
  processが同じraw_logを再試行しても(クラッシュ後の再実行等)常に同じMemory IDに
  なるようにするため。過去のレビューで、スキャンベースの連番だと再実行のたびに
  「次の空き番号」が変わってしまい、同じraw_logから複数のMemoryが重複生成される
  問題が指摘されたための対応(pipeline.py参照)。
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


_RAW_PREFIX = "raw_"
_MEM_PREFIX = "mem_"


def derive_memory_id(raw_log_id: str) -> str:
    """Memory IDをraw_log_idから決定的に導出する(1つのraw_logからは高々1つの
    Memoryしか作らない、というPhase 1/2の設計が前提。将来1つのcaptureを複数の
    Memoryへ分割するようになった場合は、この対応関係自体を見直す必要がある)。"""
    if not raw_log_id.startswith(_RAW_PREFIX):
        raise ValueError(f"raw_log_idの形式が不正です: {raw_log_id!r}")
    return _MEM_PREFIX + raw_log_id[len(_RAW_PREFIX) :]
