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

# legacy(entity_detailsを持たない旧形式)Entityのconfidenceフォールバック値。
# 詳しい根拠は entity_objects() のdocstringを参照。
_LEGACY_ENTITY_CONFIDENCE = 0.3
_LEGACY_ENTITY_METHOD = "legacy"


def _folder_for_type(config: Config, mem_type: MemoryType) -> Path:
    parts = MEMORY_TYPE_FOLDER[mem_type]
    folder = config.vault_dir
    for part in parts:
        folder = folder / part
    return folder


def _memory_path(config: Config, memory_id: str, mem_type: MemoryType) -> Path:
    return _folder_for_type(config, mem_type) / f"{memory_id}.md"


class DuplicateMemoryError(RuntimeError):
    """同一のMemory IDを持つファイルがVault内の複数のtypeフォルダに存在する異常な
    状態を検出した場合に送出する。

    通常はこの状態にはならない(find_existingが常にVault全体からIDを探すため、
    分類結果のtypeが変わっても既存ファイルを検出して再利用し、新しいtypeの
    フォルダへ複製を作ることはない)。それでも発生した場合、どちらを正として
    扱うべきかは自動では判断できない情報(手動編集、旧バージョンでの不具合等)
    に依存しうるため、黙って片方を選ぶのではなく明示的に例外にして人間の確認を
    求める。"""


def _candidate_paths(config: Config, memory_id: str) -> list[Path]:
    """Memoryが置かれうる場所は MEMORY_TYPE_FOLDER にある有限個(現在10種類)の
    type別フォルダに限られる、というVaultの構成上の不変条件を使って候補を絞り込む。

    Vault全体をrglobで再帰的に走査すると、探索コストがVaultの総ファイル数
    (Raw Log・Daily Log・添付ファイル等も含む)に比例して増え続けてしまうが、
    ここでは候補数がtypeの種類数のまま固定されるため、Vaultがどれだけ育っても
    このコストは増えない。"""
    return [_memory_path(config, memory_id, mem_type) for mem_type in MEMORY_TYPE_FOLDER]


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


def find_existing(config: Config, memory_id: str) -> Memory | None:
    """指定したIDのMemoryが既にVaultへ書き込み済みかどうかを、Vault全体(type別
    フォルダすべて)から確認する。

    Memory IDはraw_log_idから決定的に導出される(ids.derive_memory_id)ため、
    processが同じraw_logを再試行した場合(前回の実行がMemory書き込み後・SQLite
    反映前にクラッシュしたケース)、この関数がファイルの存在を検出することで、
    pipeline.py が新しいMemoryを二重に作らず、書き込み済みの内容をそのまま
    正として使えるようになる(指示書25章: Markdownが正本)。

    【2回目のレビュー対応】以前は「現在の分類結果が示すtypeのフォルダ」1箇所しか
    見ていなかった。しかしクラッシュ・再試行の間に分類ロジック自体が変わっていた
    場合(例: 同じ入力が前回はTHOUGHT、今回はDECISIONに分類される)、旧typeの
    フォルダに書き込み済みの既存ファイルを見失い、新しいtypeのフォルダへ同じIDの
    Memoryを重複生成してしまう。そのため、呼び出し側がどのtypeを想定しているかに
    関わらず、Vault内の全typeフォルダを対象に探す。

    同じIDが複数のtypeフォルダに見つかった場合はDuplicateMemoryErrorを送出する
    (自動的にどちらかを選ばない)。"""
    found = [p for p in _candidate_paths(config, memory_id) if p.exists()]
    if len(found) > 1:
        raise DuplicateMemoryError(
            f"Memory ID '{memory_id}' が複数の場所に存在します: " + ", ".join(str(p) for p in found)
        )
    if not found:
        return None
    return read_memory(found[0], config)


def entity_objects(memory: Memory) -> list[ExtractedEntity]:
    """memory.entity_details(name/confidence/method)があればそれを ExtractedEntity へ
    復元する。無ければ memory.entities(名前のみ)から後方互換用のフォールバックを
    組み立てる(entity_detailsが存在しなかった時点、すなわちconfidenceによる
    重み付けそのものが導入される前に書かれたMemoryファイルでも壊れずに動く)。

    【2回目のレビュー対応】このフォールバックのconfidenceは、以前は1.0(=最大の
    信頼度)だった。これは方向が逆である。entity_detailsが無いということは、
    その値は「confidenceという概念が導入される前」の抽出器(entity_extract.pyの
    カタカナヒューリスティックの最初期版)が出したものであり、その版は
    「カタカナ連続2文字以上ならほぼ無条件にentityとみなす」というルールしか
    持たず、"アプリ"「スマホ」のような一般的な外来語を選別なく拾っていた
    (現行版で追加された_GENERIC_HINTSによる減点や、語長に基づく基礎confidence
    の考え方が一切ない)。つまりlegacyデータは現行のconfidence設計から見て
    「精度が現行の最低ラインより低い」側であり、1.0(最も信頼できる)は実態と
    逆になる。

    そこで_LEGACY_ENTITY_CONFIDENCE=0.3を採用する。これは現行のentity_extract.py
    において、既知の一般語リストに載っていない通常の語であっても、最短カテゴリ
    (カタカナ2文字)に基礎confidenceとして割り当てられる最も低い値
    (_base_confidence(2) == 0.3)と同じ水準であり、「legacy抽出はどんな語であれ、
    現行ヒューリスティックが付けうる最も慎重な評価と同程度にしか信頼しない」という
    保守的な扱いになる(既知の一般語であれば現行版はさらに0.4倍の減点を加えて
    0.12まで下げるが、legacyデータは個々の語がどちらだったか区別する情報を
    持たないため、その最低ラインまでは下げず0.3に留める)。

    下流のlinking.py側では、same_entityの強さを
    min(target_confidence, candidate_confidence) で計算しているため、0.3という
    低いconfidenceは「legacy側の一般語1件だけの一致が、単独で強いリンクの根拠には
    ならない」という設計にも自然に整合する。"""
    if memory.entity_details:
        return [
            ExtractedEntity(
                name=d["name"],
                confidence=float(d.get("confidence", _LEGACY_ENTITY_CONFIDENCE)),
                method=str(d.get("method", _LEGACY_ENTITY_METHOD)),
            )
            for d in memory.entity_details
        ]
    return [
        ExtractedEntity(name=name, confidence=_LEGACY_ENTITY_CONFIDENCE, method=_LEGACY_ENTITY_METHOD)
        for name in memory.entities
    ]


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
