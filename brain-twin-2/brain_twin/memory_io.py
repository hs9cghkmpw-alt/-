"""Layer 3 (Long-term Memory) の読み書き(指示書5・6・7章)。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from brain_twin import frontmatter as fm
from brain_twin import ids, vault
from brain_twin.config import Config
from brain_twin.models import (
    MEMORY_TYPE_FOLDER,
    ClassificationResult,
    ExtractedEntity,
    Memory,
    MemoryStatus,
    MemoryType,
    RawLog,
)


def _folder_for_type(config: Config, mem_type: MemoryType) -> Path:
    parts = MEMORY_TYPE_FOLDER[mem_type]
    folder = config.vault_dir
    for part in parts:
        folder = folder / part
    return folder


def _memory_path(config: Config, memory_id: str, mem_type: MemoryType) -> Path:
    return _folder_for_type(config, mem_type) / f"{memory_id}.md"


def build_memory(raw_log: RawLog, classification: ClassificationResult, dt: datetime | None = None) -> Memory:
    dt = dt or datetime.fromisoformat(raw_log.created_at)
    return Memory(
        id=ids.derive_memory_id(raw_log.id),
        type=classification.type,
        created_at=dt.isoformat(),
        event_date=dt.strftime("%Y-%m-%d"),
        importance=classification.importance,
        confidence=classification.confidence,
        source=raw_log.source,
        status=MemoryStatus.ACTIVE,
        title=classification.title or raw_log.text[:24],
        content=raw_log.text,
        raw_log_id=raw_log.id,
        topics=classification.topics,
        entities=[e.name for e in classification.entities],
        entity_details=[{"name": e.name, "confidence": e.confidence, "method": e.method} for e in classification.entities],
        links=[],
        link_details=[],
    )


def find_existing(config: Config, memory_id: str, mem_type: MemoryType) -> Memory | None:
    """指定したIDのMemoryが既にVaultへ書き込み済みかどうかを確認する。

    Memory IDはraw_log_idから決定的に導出される(ids.derive_memory_id)ため、
    processが同じraw_logを再試行した場合(前回の実行がMemory書き込み後・SQLite
    反映前にクラッシュしたケース)、この関数がファイルの存在を検出することで、
    pipeline.py が新しいMemoryを二重に作らず、書き込み済みの内容をそのまま
    正として使えるようになる(指示書25章: Markdownが正本)。"""
    path = _memory_path(config, memory_id, mem_type)
    if not path.exists():
        return None
    return read_memory(path, config)


def entity_objects(memory: Memory) -> list[ExtractedEntity]:
    """memory.entity_details(name/confidence/method)があればそれを ExtractedEntity へ
    復元する。無ければ memory.entities(名前のみ)から confidence=1.0 のフォールバックを
    組み立てる(後方互換性: このフィールドが存在しなかった時点で書かれたMemoryファイル
    でも壊れずに動く)。"""
    if memory.entity_details:
        return [
            ExtractedEntity(
                name=d["name"],
                confidence=float(d.get("confidence", 1.0)),
                method=str(d.get("method", "legacy")),
            )
            for d in memory.entity_details
        ]
    return [ExtractedEntity(name=name, confidence=1.0, method="legacy") for name in memory.entities]


def write_memory(config: Config, memory: Memory) -> Memory:
    if not memory.id:
        raise ValueError("Memory.id が未設定です。build_memory() 経由で決定的に採番してから呼び出してください。")

    path = _memory_path(config, memory.id, memory.type)
    path.parent.mkdir(parents=True, exist_ok=True)

    front = {
        "id": memory.id,
        "type": memory.type.value,
        "created": memory.created_at,
        "event_date": memory.event_date,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "source": memory.source,
        "status": memory.status.value,
        "topics": memory.topics,
        "entities": memory.entities,
        "entity_details": memory.entity_details,
        "links": memory.links,
        "link_details": memory.link_details,
        "raw_log_id": memory.raw_log_id,
    }
    body = (
        f"# {memory.title}\n\n"
        f"{memory.content}\n\n"
        f"## Source\n"
        f"- raw_log_id: {memory.raw_log_id or '(なし)'}\n"
        f"- source: {memory.source}\n"
        f"- created: {memory.created_at}\n"
    )
    vault.write_text_atomic(path, fm.dump(front, body))
    memory.file_path = vault.relative_to_vault(path, config)
    return memory


def read_memory(path: Path, config: Config) -> Memory:
    parsed = fm.parse(path.read_text(encoding="utf-8"))
    front = parsed.frontmatter
    body_lines = parsed.body.splitlines()

    title = ""
    content_lines: list[str] = []
    in_content = False
    for line in body_lines:
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            in_content = True
            continue
        if line.strip() == "## Source":
            break
        if in_content:
            content_lines.append(line)
    content = "\n".join(content_lines).strip()

    return Memory(
        id=front["id"],
        type=MemoryType(front["type"]),
        created_at=front["created"],
        event_date=front["event_date"],
        importance=int(front["importance"]),
        confidence=float(front["confidence"]),
        source=front.get("source", "unknown"),
        status=MemoryStatus(front.get("status", "active")),
        title=title,
        content=content,
        raw_log_id=front.get("raw_log_id"),
        topics=list(front.get("topics") or []),
        entities=list(front.get("entities") or []),
        entity_details=list(front.get("entity_details") or []),
        links=list(front.get("links") or []),
        link_details=list(front.get("link_details") or []),
        file_path=vault.relative_to_vault(path, config),
    )


def list_all_memories(config: Config) -> list[Memory]:
    if not config.memory_dir.exists() and not config.vault_dir.exists():
        return []
    memories: list[Memory] = []
    for folder_parts in MEMORY_TYPE_FOLDER.values():
        folder = config.vault_dir
        for part in folder_parts:
            folder = folder / part
        if not folder.exists():
            continue
        for path in sorted(folder.glob("mem_*.md")):
            memories.append(read_memory(path, config))
    return memories
