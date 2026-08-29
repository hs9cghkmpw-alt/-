"""Harder deterministic open-development organizer corpus layered on open v1."""
from __future__ import annotations

from datetime import datetime, timedelta

from brain_twin_eval.organizer import (
    OrganizerContextMemory,
    OrganizerDataset,
    OrganizerGold,
    OrganizerSample,
)
from brain_twin_eval.organizer_gold import build_organizer_open_v1


def build_organizer_open_v2() -> OrganizerDataset:
    samples = list(build_organizer_open_v1().samples)

    for i in range(1, 9):
        created = datetime.fromisoformat(f"2026-08-{10 + i:02d}T10:00:00+09:00")
        created_at = created.isoformat()
        yesterday = (created.date() - timedelta(days=1)).isoformat()
        tomorrow = (created.date() + timedelta(days=1)).isoformat()

        samples.append(
            _sample(
                f"org-v2-relative-yesterday-{i:02d}",
                f"昨日、架空の夕凪公園{i}を散歩した。思ったより静かで30分くらい歩けた。",
                created_at,
                "experience",
                ("health",),
                (f"夕凪公園{i}",),
                yesterday,
                2,
                ("relative_date", "date_present", "experience", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-v2-relative-tomorrow-{i:02d}",
                f"明日、架空チーム ミスト{i}とのレビューを実施すると決めた。",
                created_at,
                "decision",
                ("work",),
                (f"ミスト{i}",),
                tomorrow,
                3,
                ("relative_date", "date_present", "decision_explicit", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-v2-cancelled-{i:02d}",
                f"アクアギア{i}を買う予定だったけど、今回は買わないと決めた。必要なら来年また考える。",
                created_at,
                "decision",
                ("money", "hobby"),
                (f"アクアギア{i}",),
                None,
                2,
                ("negation", "cancelled_intention", "decision_explicit", "date_absent", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-v2-uncertain-{i:02d}",
                f"来月あたりから朝に散歩できたらいいかもしれない。まだ予定にはしていない。案{i}。",
                created_at,
                "thought",
                ("health", "idea"),
                (),
                None,
                1,
                ("uncertainty", "vague_date", "not_decided", "date_absent", "thought"),
            )
        )
        samples.append(
            _sample(
                f"org-v2-quote-{i:02d}",
                f"架空人物 ナオ{i}は赤い釣具が好きだと言っていた。でも私は青くてシンプルな物の方が好き。",
                created_at,
                "preference",
                ("hobby",),
                (f"ナオ{i}",),
                None,
                2,
                ("quoted_statement", "attribution", "preference", "date_absent", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-v2-multi-date-{i:02d}",
                f"2026年7月{i + 10}日に計画を話した。目標は2026年9月{i + 10}日までに架空ツール セレス{i}の移行を終えること。",
                created_at,
                "goal",
                ("work", "technology"),
                (f"セレス{i}",),
                f"2026-09-{i + 10:02d}",
                4,
                ("multiple_dates", "deadline_selection", "goal", "date_present", "entity"),
            )
        )
        samples.append(
            _sample(
                f"org-v2-not-decided-{i:02d}",
                f"架空サービス フロスト{i}へ移行する案は良さそう。ただし、まだ移行すると決めたわけではない。",
                created_at,
                "thought",
                ("work", "technology", "idea"),
                (f"フロスト{i}",),
                None,
                3,
                ("type_ambiguity", "not_decided", "negation", "thought", "date_absent", "entity"),
            )
        )

        context = (
            OrganizerContextMemory(
                memory_id=f"ctx-v2-storage-{i:02d}",
                title=f"オリオン{i}の端末内保存",
                summary="オリオンの端末内保存方針を決めた過去メモ。",
            ),
            OrganizerContextMemory(
                memory_id=f"ctx-v2-backup-{i:02d}",
                title=f"オリオン{i}のバックアップ検討",
                summary="バックアップ先と復旧手順を比較した別件のメモ。",
            ),
            OrganizerContextMemory(
                memory_id=f"ctx-v2-unrelated-{i:02d}",
                title="旅行の持ち物",
                summary="週末旅行の持ち物リスト。",
            ),
        )
        samples.append(
            _sample(
                f"org-v2-link-hard-{i:02d}",
                f"オリオン{i}のバックアップ復旧手順を詰めたい。前に決めた端末内保存そのものとは別件。",
                created_at,
                "thought",
                ("work", "technology"),
                (f"オリオン{i}",),
                None,
                3,
                ("link_hard_negative", "context_disambiguation", "negation", "entity"),
                context=context,
                links=(f"ctx-v2-backup-{i:02d}",),
            )
        )

    return OrganizerDataset(
        version="organizer-open-v2",
        judgement_visibility="open",
        samples=tuple(samples),
    )


def _sample(
    sample_id: str,
    raw_text: str,
    created_at: str,
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
            memory_worthy=True,
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
