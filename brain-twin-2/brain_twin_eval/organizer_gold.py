"""Deterministic privacy-safe open-development gold for organizer LLM evaluation."""
from __future__ import annotations

from brain_twin_eval.organizer import (
    OrganizerContextMemory,
    OrganizerDataset,
    OrganizerGold,
    OrganizerSample,
)


def build_organizer_open_v1() -> OrganizerDataset:
    samples: list[OrganizerSample] = []
    created_at = "2026-08-15T10:00:00+09:00"

    for i in range(1, 9):
        may_day = 10 + i
        july_day = 8 + i
        oct_day = 10 + i

        samples.append(
            _sample(
                f"org-decision-{i:02d}",
                f"2026-05-{may_day:02d}に、架空プロジェクト オリオン{i}では端末内保存を優先すると決めた。",
                created_at,
                True,
                "decision",
                ("work", "technology"),
                (f"オリオン{i}",),
                f"2026-05-{may_day:02d}",
                4,
                ("decision_explicit", "date_present", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-goal-{i:02d}",
                f"2026年9月30日までに英語の技術記事を毎週2本読めるようにしたい。第{i}期の目標。",
                created_at,
                True,
                "goal",
                ("learning",),
                (),
                "2026-09-30",
                3,
                ("goal", "date_present"),
            )
        )
        samples.append(
            _sample(
                f"org-preference-{i:02d}",
                f"釣りでは派手な装備より、軽くて片付けやすい道具の方が好き。候補{i}でもこの基準を優先したい。",
                created_at,
                True,
                "preference",
                ("hobby",),
                (),
                None,
                2,
                ("preference", "date_absent"),
            )
        )
        samples.append(
            _sample(
                f"org-experience-{i:02d}",
                f"2026-07-{july_day:02d}に青葉港{i}へ行った。風が強く、予定より早く切り上げた。",
                created_at,
                True,
                "experience",
                ("hobby", "travel"),
                (f"青葉港{i}",),
                f"2026-07-{july_day:02d}",
                2,
                ("experience", "date_present", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-thought-{i:02d}",
                f"Brain Twinの検索は、完全一致より『前に考えていたあれ』を拾える方が重要だと思う。観点{i}。",
                created_at,
                True,
                "thought",
                ("technology", "idea"),
                ("Brain Twin",),
                None,
                3,
                ("thought", "date_absent", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-fact-{i:02d}",
                f"ミナトラボ{i}との次回ミーティングは2026-09-{i + 10:02d}の14時に決まっている。",
                created_at,
                True,
                "fact",
                ("work",),
                (f"ミナトラボ{i}",),
                f"2026-09-{i + 10:02d}",
                3,
                ("fact", "date_present", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-knowledge-{i:02d}",
                f"BM25は語の出現頻度と文書頻度を使う検索ランキング手法。メモ{i}として残す。",
                created_at,
                True,
                "knowledge",
                ("technology", "learning"),
                ("BM25",),
                None,
                2,
                ("knowledge", "date_absent", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-project-{i:02d}",
                f"架空プロジェクト ルミナ{i}は、オフラインで動く個人用整理アプリとして進めている。",
                created_at,
                True,
                "project",
                ("work", "technology"),
                (f"ルミナ{i}",),
                None,
                3,
                ("project", "date_absent", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-person-{i:02d}",
                f"架空人物 ナギサ{i}はデータ整理を担当しており、短い要点メモを好む。",
                created_at,
                True,
                "person",
                ("work",),
                (f"ナギサ{i}",),
                None,
                2,
                ("person", "date_absent", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-chat-{i:02d}",
                f"了解です{i}",
                created_at,
                False,
                "thought",
                (),
                (),
                None,
                1,
                ("non_memory", "short_input", "date_absent"),
            )
        )
        samples.append(
            _sample(
                f"org-multitopic-{i:02d}",
                f"家族旅行の予算を3万円以内にして、移動時間も短くしたい。候補{i}をあとで比較する。",
                created_at,
                True,
                "thought",
                ("family", "money", "travel"),
                (),
                None,
                3,
                ("multi_topic", "date_absent"),
            )
        )

        context = (
            OrganizerContextMemory(
                memory_id=f"ctx-storage-{i:02d}",
                title=f"オリオン{i}の保存方針",
                summary="端末内保存を優先するという過去の決定。",
            ),
            OrganizerContextMemory(
                memory_id=f"ctx-ui-{i:02d}",
                title=f"オリオン{i}の画面配色",
                summary="画面配色の候補を比較したメモ。",
            ),
            OrganizerContextMemory(
                memory_id=f"ctx-trip-{i:02d}",
                title="旅行候補",
                summary="週末旅行の候補地を比較したメモ。",
            ),
        )
        samples.append(
            _sample(
                f"org-link-{i:02d}",
                f"オリオン{i}は前に決めた端末内保存の方針を変えず、その前提で同期処理を考えたい。",
                created_at,
                True,
                "thought",
                ("work", "technology"),
                (f"オリオン{i}",),
                None,
                3,
                ("link_candidate", "context_disambiguation", "entity"),
                context=context,
                links=(f"ctx-storage-{i:02d}",),
            )
        )
        samples.append(
            _sample(
                f"org-entities-{i:02d}",
                f"ノーススター{i}とブルーリーフ{i}を比較したところ、今回はノーススター{i}の方が設定が単純だった。",
                created_at,
                True,
                "experience",
                ("technology",),
                (f"ノーススター{i}", f"ブルーリーフ{i}"),
                None,
                2,
                ("multi_entity", "entity_distractor", "date_absent"),
            )
        )
        samples.append(
            _sample(
                f"org-nodate-{i:02d}",
                f"部屋の作業机は物を置きすぎない方が集中しやすい気がする。整理案{i}。",
                created_at,
                True,
                "thought",
                ("home",),
                (),
                None,
                2,
                ("date_absent", "thought"),
            )
        )
        samples.append(
            _sample(
                f"org-important-{i:02d}",
                f"2026-10-{oct_day:02d}に家族でさくら町{i}へ引っ越す方針を最優先で進めると決めた。",
                created_at,
                True,
                "decision",
                ("family", "home"),
                (f"さくら町{i}",),
                f"2026-10-{oct_day:02d}",
                5,
                ("high_importance", "decision_explicit", "date_present", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-mixed-{i:02d}",
                f"Project Vega{i}のoffline modeを2026年12月31日までに完成させたい。日本語UIも同じリリースに入れる。",
                created_at,
                True,
                "goal",
                ("work", "technology"),
                (f"Project Vega{i}",),
                "2026-12-31",
                4,
                ("mixed_jp_en", "goal", "date_present", "entity"),
            )
        )

    return OrganizerDataset(
        version="organizer-open-v1",
        judgement_visibility="open",
        samples=tuple(samples),
    )


def _sample(
    sample_id: str,
    raw_text: str,
    created_at: str,
    memory_worthy: bool,
    memory_type: str,
    topics: tuple[str, ...],
    entities: tuple[str, ...],
    event_date: str | None,
    importance: int,
    slices: tuple[str, ...],
    *,
    context: tuple[OrganizerContextMemory, ...] = (),
    links: tuple[str, ...] = (),
) -> OrganizerSample:
    return OrganizerSample(
        sample_id=sample_id,
        raw_text=raw_text,
        created_at=created_at,
        gold=OrganizerGold(
            memory_worthy=memory_worthy,
            memory_type=memory_type,
            topics=topics,
            entities=entities,
            event_date=event_date,
            importance=importance,
            link_candidates=links,
        ),
        slices=slices,
        context_memories=context,
    )
