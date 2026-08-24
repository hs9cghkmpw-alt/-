"""Layer 1 (Raw Log: 00_Inbox) と Layer 2 (Daily Log: 10_Daily) の読み書き
(指示書4章)。原文は改変禁止のため、一度書いたraw logの本文には二度と触らない
(処理済みフラグの更新以外は追記のみ)。

【2回目のレビュー対応】書き込みは全て vault.write_text_atomic() 経由にしている。
Raw LogはVaultの中で最も失ってはいけない原本(Markdown化する前の入力そのもの)
であり、少なくともMemory Markdownと同等以上に書き込み途中のクラッシュに強くある
べきという指摘に基づく。Daily Logも同じ理由で対象にした。

【3回目のレビュー対応】mark_processed()がfrontmatterへ書き込む processing_outcome /
memory_id は、「そのraw logが処理された時点で実際にどう判断されたか」を記録する
ための最小限のメタデータ。reconcile.py がクラッシュ復旧時にこれを読むことで、
現在のclassifierを再実行して過去の判断を再解釈することを避けられる
(指示書25章: 過去に確定した処理結果はMarkdownが正本であり、現在の実装で
再解釈しない、という原則)。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from brain_twin import frontmatter as fm
from brain_twin import ids, vault
from brain_twin.config import Config
from brain_twin.models import RawLog

# raw_log.processing_outcome に書き込む値。Memory化されたか、雑談としてDaily Logのみに
# 残されたか(Long-term Memoryに昇格しなかったか)の2択。
PROCESSING_OUTCOME_MEMORY = "memory"
PROCESSING_OUTCOME_CHAT = "chat"


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
    vault.write_text_atomic(path, fm.dump(front, text))

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
        # 旧形式のraw log(このフィールドが導入される前に処理されたもの)には
        # 存在しないため、.get()でNoneにフォールバックする(後方互換)。
        processing_outcome=front.get("processing_outcome"),
        memory_id=front.get("memory_id"),
    )


def list_raw_logs(config: Config, *, unprocessed_only: bool = False) -> list[RawLog]:
    if not config.inbox_dir.exists():
        return []
    logs = [read_raw_log(p, config) for p in sorted(config.inbox_dir.glob("raw_*.md"))]
    if unprocessed_only:
        logs = [log for log in logs if log.processed_at is None]
    return sorted(logs, key=lambda r: r.created_at)


def mark_processed(
    config: Config,
    raw_log: RawLog,
    *,
    processing_outcome: str | None = None,
    memory_id: str | None = None,
    processed_at: datetime | None = None,
) -> None:
    """Raw Logのfrontmatterへ processed_at(必須)と、その処理結果
    (processing_outcome / memory_id、任意)を書き込む。

    processing_outcome/memory_idを渡さない呼び出し方も引き続きサポートする
    (テストや、結果を記録する必要が無い呼び出し元のため)。渡された場合のみ
    frontmatterへ反映し、渡されなければ既存のfrontmatterを変更しない。"""
    processed_at = processed_at or datetime.now().astimezone()
    path = config.vault_dir / raw_log.file_path
    parsed = fm.parse(path.read_text(encoding="utf-8"))
    parsed.frontmatter["processed_at"] = processed_at.isoformat()
    if processing_outcome is not None:
        parsed.frontmatter["processing_outcome"] = processing_outcome
        raw_log.processing_outcome = processing_outcome
    if memory_id is not None:
        parsed.frontmatter["memory_id"] = memory_id
        raw_log.memory_id = memory_id
    vault.write_text_atomic(path, fm.dump(parsed.frontmatter, parsed.body))
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

    vault.write_text_atomic(path, fm.dump(front, body))
    return path
