"""型定義(指示書5章 Memory Type、7章 Markdown Memory Format に対応)。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MemoryType(str, Enum):
    FACT = "fact"
    EXPERIENCE = "experience"
    THOUGHT = "thought"
    DECISION = "decision"
    PREFERENCE = "preference"
    GOAL = "goal"
    KNOWLEDGE = "knowledge"
    PERSON = "person"
    PROJECT = "project"
    AI_INFERENCE = "ai_inference"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


# MemoryType -> Vault内の保存先フォルダ(指示書6章の構成に対応)。
# 20_Memory/配下に無い型(knowledge/person/project/ai_inference)は、
# 名称が対応するVault直下のフォルダへ振り分ける。
MEMORY_TYPE_FOLDER: dict[MemoryType, tuple[str, ...]] = {
    MemoryType.EXPERIENCE: ("20_Memory", "Experiences"),
    MemoryType.THOUGHT: ("20_Memory", "Thoughts"),
    MemoryType.DECISION: ("20_Memory", "Decisions"),
    MemoryType.PREFERENCE: ("20_Memory", "Preferences"),
    MemoryType.GOAL: ("20_Memory", "Goals"),
    MemoryType.FACT: ("20_Memory", "Facts"),
    MemoryType.KNOWLEDGE: ("40_Knowledge",),
    MemoryType.PERSON: ("50_People",),
    MemoryType.PROJECT: ("30_Projects",),
    MemoryType.AI_INFERENCE: ("80_AI",),
}


@dataclass
class RawLog:
    id: str
    text: str
    source: str
    created_at: str  # ISO8601
    file_path: str  # vaultルートからの相対パス
    processed_at: str | None = None


@dataclass
class DailyLogEntry:
    raw_log_id: str
    time_label: str  # "06:31" 等、表示用
    text: str


@dataclass
class Memory:
    id: str
    type: MemoryType
    created_at: str  # ISO8601
    event_date: str  # YYYY-MM-DD
    importance: int  # 1-5
    confidence: float  # 0.0-1.0
    source: str
    status: MemoryStatus
    title: str
    content: str
    raw_log_id: str | None
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)  # Obsidian向け "[[mem_id]]" 形式(指示書7章の例に合わせる)
    # links と同じ内容を relation_type/reason 付きで保持する(指示書25章: SQLiteをMarkdownから
    # 完全に再構築するには、リンクの種類・理由もMarkdown側に残っている必要があるため)。
    link_details: list[dict] = field(default_factory=list)
    file_path: str = ""  # vaultルートからの相対パス。書き込み時に確定する。


@dataclass
class ClassificationResult:
    """Phase 1のダミー分類器の出力。将来LLMベースの分類器に差し替える際も
    このデータ形状は変えない想定(指示書23章 LLM非依存の思想を、この最小単位でも維持する)。"""

    is_memory_worthy: bool
    type: MemoryType
    importance: int
    confidence: float
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    title: str = ""
