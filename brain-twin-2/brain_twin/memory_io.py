"""Layer 3 (Long-term Memory) の読み書き(指示書5・6・7章)。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from brain_twin import frontmatter as fm
from brain_twin import ids, vault
from brain_twin.config import Config
from brain_twin.models import MEMORY_TYPE_FOLDER, ClassificationResult, Memory, MemoryStatus, MemoryType, RawLog


def _folder_for_type(config: Config, mem_type: MemoryType) -> Path:
    parts = MEMORY_TYPE_FOLDER[mem_type]
    folder = config.vault_dir
    for part in parts:
        folder = folder / part
    return folder


def build_memory(raw_log: RawLog, classification: ClassificationResult, dt: datetime | None = None) -> Memory:
    dt = dt or datetime.fromisoformat(raw_log.created_at)
    return Memory(
        id="",  # write_memoryで確定させる
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
        entities=classification.entities,
        links=[],
    )


def write_memory(config: Config, memory: Memory) -> Memory:
    if not memory.id:
        dt_for_id = datetime.fromisoformat(memory.created_at)
        memory.id = ids.new_id(config.vault_dir, "mem", dt_for_id)

    folder = _folder_for_type(config, memory.type)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{memory.id}.md"

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
        "links": memory.links,
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
    path.write_text(fm.dump(front, body), encoding="utf-8")
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
        links=list(front.get("links") or []),
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
