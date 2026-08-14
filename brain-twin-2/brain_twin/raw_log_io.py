"""Layer 1 (Raw Log: 00_Inbox) と Layer 2 (Daily Log: 10_Daily) の読み書き
(指示書4章)。原文は改変禁止のため、一度書いたraw logの本文には二度と触らない
(処理済みフラグの更新以外は追記のみ)。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from brain_twin import frontmatter as fm
from brain_twin import ids, vault
from brain_twin.config import Config
from brain_twin.models import RawLog


def write_raw_log(config: Config, text: str, source: str, dt: datetime | None = None) -> RawLog:
    dt = dt or datetime.now().astimezone()
    raw_id = ids.new_id(config.vault_dir, "raw", dt)
    path = config.inbox_dir / f"{raw_id}.md"

    front = {
        "id": raw_id,
        "created": dt.isoformat(),
        "source": source,
        "processed_at": None,
    }
    path.write_text(fm.dump(front, text), encoding="utf-8")

    return RawLog(
        id=raw_id,
        text=text.strip(),
        source=source,
        created_at=dt.isoformat(),
        file_path=vault.relative_to_vault(path, config),
        processed_at=None,
    )


def read_raw_log(path: Path, config: Config) -> RawLog:
    parsed = fm.parse(path.read_text(encoding="utf-8"))
    front = parsed.frontmatter
    return RawLog(
        id=front["id"],
        text=parsed.body.strip(),
        source=front.get("source", "unknown"),
        created_at=front["created"],
        file_path=vault.relative_to_vault(path, config),
        processed_at=front.get("processed_at"),
    )


def list_raw_logs(config: Config, *, unprocessed_only: bool = False) -> list[RawLog]:
    if not config.inbox_dir.exists():
        return []
    logs = [read_raw_log(p, config) for p in sorted(config.inbox_dir.glob("raw_*.md"))]
    if unprocessed_only:
        logs = [log for log in logs if log.processed_at is None]
    return sorted(logs, key=lambda r: r.created_at)


def mark_processed(config: Config, raw_log: RawLog, processed_at: datetime | None = None) -> None:
    processed_at = processed_at or datetime.now().astimezone()
    path = config.vault_dir / raw_log.file_path
    parsed = fm.parse(path.read_text(encoding="utf-8"))
    parsed.frontmatter["processed_at"] = processed_at.isoformat()
    path.write_text(fm.dump(parsed.frontmatter, parsed.body), encoding="utf-8")
    raw_log.processed_at = processed_at.isoformat()


def _daily_log_path(config: Config, date_str: str) -> Path:
    return config.daily_dir / f"{date_str}.md"


def append_to_daily_log(config: Config, raw_log: RawLog) -> Path:
    """raw_logをその日のDaily Logへ追記する。同じraw_logを二重に追記しないよう、
    既に記録済みのraw_log_idならスキップする(冪等)。"""
    created = datetime.fromisoformat(raw_log.created_at)
    date_str = created.strftime("%Y-%m-%d")
    time_label = created.strftime("%H:%M")
    path = _daily_log_path(config, date_str)

    if path.exists():
        parsed = fm.parse(path.read_text(encoding="utf-8"))
        front = parsed.frontmatter
        body = parsed.body
    else:
        front = {"date": date_str, "raw_log_ids": []}
        body = f"# {date_str} Daily Log\n"

    raw_log_ids = front.setdefault("raw_log_ids", [])
    if raw_log.id in raw_log_ids:
        return path  # 既に追記済み(冪等)

    raw_log_ids.append(raw_log.id)
    body = body.rstrip("\n") + f"\n\n## {time_label}\n{raw_log.text}\n"

    path.write_text(fm.dump(front, body), encoding="utf-8")
    return path
