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


@dataclass(frozen=True)
class ExtractedEntity:
    """Entity抽出結果1件分。抽出手法が変わっても(Phase 2のカタカナヒューリスティック→
    将来のLLM/NLPベース抽出)、この3つのフィールドさえ返せば下流(linking.py等)を
    変更せずに済むようにするための共通インターフェース(指示書23章 LLM非依存の思想を、
    Entity抽出の単位でも維持する)。

    confidenceは「この抽出がどの程度信頼できるか」(0.0-1.0)。低いconfidenceの一致を
    強いリンクの根拠にしない、という判断はlinking.py側の責務とし、ここでは値を
    持たせるだけに留める。"""

    name: str
    confidence: float
    method: str


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
    entities: list[str] = field(default_factory=list)  # 表示用のシンプルな名前一覧
    # entities と同じ内容を confidence/method 付きで保持する(過去のレビュー指摘:
    # 精度の低いEntity抽出結果がstrengthの強いリンクの根拠になっていた問題への対応。
    # linking.py がconfidenceを考慮できるよう、reindex/再実行でも復元できる形でここに残す)。
    entity_details: list[dict] = field(default_factory=list)
    links: list[str] = field(default_factory=list)  # Obsidian向け "[[mem_id]]" 形式(指示書7章の例に合わせる)
    # links と同じ内容を relation_type/reason/created_at 付きで保持する(指示書25章:
    # SQLiteをMarkdownから完全に再構築するには、リンクの種類・理由・生成時刻も
    # Markdown側に残っている必要があるため)。
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
    entities: list[ExtractedEntity] = field(default_factory=list)
    title: str = ""
