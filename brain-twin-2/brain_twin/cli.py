"""CLIエントリポイント(指示書29・35・37章)。"""
from __future__ import annotations

import argparse
import sys

from brain_twin import pipeline, retrieval, search
from brain_twin.config import load_config


def _cmd_add(args: argparse.Namespace) -> int:
    config = load_config()
    try:
        raw_id = pipeline.add_capture(config, args.text, source=args.source)
    except ValueError as e:
        print(f"[NG] {e}", file=sys.stderr)
        return 1
    print(f"[OK] 保存しました ({raw_id})")
    print("   まだ整理はしていません。`python brain.py process` で整理されます。")
    return 0


def _cmd_process(args: argparse.Namespace) -> int:
    config = load_config()
    summary = pipeline.process_all(config)

    if summary.total_inputs == 0:
        print("未処理の入力はありません。")
        return 0

    print(f"今日の入力: {summary.total_inputs}件")
    print(f"Daily Logへ保存: {summary.daily_log_saved}件")
    print(f"Long-term Memory候補: {summary.memories_created}件")
    print(f"雑談として保持: {summary.kept_as_chat}件")
    print(f"生成されたLink: {summary.links_created}件")
    if summary.memory_ids and args.verbose:
        print("生成されたMemory:")
        for mid in summary.memory_ids:
            print(f"  - {mid}")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    config = load_config()
    if args.related:
        try:
            retrieval_result = retrieval.retrieve_with_config(
                config, args.query, primary_limit=args.limit, related_limit=args.related_limit
            )
        except ValueError as exc:
            print(f"[NG] {exc}", file=sys.stderr)
            return 1
        results = retrieval_result.primary
    else:
        retrieval_result = None
        results = search.search_with_config(config, args.query, limit=args.limit)

    if not results:
        print("該当するMemoryが見つかりませんでした。")
        return 0

    for r in results:
        topics = ",".join(r.topics) if r.topics else "-"
        entities = ",".join(r.entities) if r.entities else "-"
        print(f"[{r.event_date}] ({r.type} / importance={r.importance} / confidence={r.confidence:.2f} / topics={topics} / entities={entities})")
        print(f"  {r.title}")
        if args.verbose:
            snippet = r.content if len(r.content) <= 120 else r.content[:120] + "…"
            print(f"  {snippet}")
        print(f"  id={r.memory_id}")
        print()
    if retrieval_result is not None and retrieval_result.related:
        print("関連Memory:")
        for item in retrieval_result.related:
            print(f"[{item.event_date}] ({item.type}) {item.title}")
            print(f"  id={item.memory_id}")
            for relation in item.relations:
                print(
                    f"  <- {relation.primary_memory_id} "
                    f"({relation.direction} / {relation.relation_type} / "
                    f"strength={relation.strength:.3f}): {relation.reason}"
                )
            if args.verbose:
                snippet = item.content if len(item.content) <= 120 else item.content[:120] + "…"
                print(f"  {snippet}")
            print()
    return 0


def _cmd_timeline(args: argparse.Namespace) -> int:
    config = load_config()
    try:
        results = search.timeline_with_config(
            config, from_date=args.from_date, to_date=args.to_date, limit=args.limit
        )
    except ValueError as exc:
        print(f"[NG] {exc}", file=sys.stderr)
        return 1
    if not results:
        print("該当するMemoryが見つかりませんでした。")
        return 0
    for item in results:
        print(f"[{item.event_date}] ({item.type}) {item.title}")
        if args.verbose:
            snippet = item.content if len(item.content) <= 120 else item.content[:120] + "…"
            print(f"  {snippet}")
        print(f"  id={item.memory_id}")
        print()
    return 0


def _cmd_reindex(args: argparse.Namespace) -> int:
    config = load_config()
    counts = pipeline.reindex(config)
    print("SQLite indexをVaultから再構築しました。")
    print(f"  raw_logs: {counts['raw_logs']}件")
    print(f"  daily_logs: {counts['daily_logs']}件")
    print(f"  memories: {counts['memories']}件")
    print(f"  links: {counts['links']}件")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brain.py", description="Brain Twin 2.0 (Phase 3: Retrieval)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="思ったことをそのまま記録する(整理はしない)")
    p_add.add_argument("text", help="記録したい内容")
    p_add.add_argument("--source", default="cli", help="入力元 (既定: cli)")
    p_add.set_defaults(func=_cmd_add)

    p_process = sub.add_parser("process", help="未処理の入力をDaily Log/Memoryへ整理する")
    p_process.add_argument("-v", "--verbose", action="store_true", help="生成したMemory IDも表示する")
    p_process.set_defaults(func=_cmd_process)

    p_search = sub.add_parser("search", help="Memoryを検索する")
    p_search.add_argument("query", help="検索キーワード")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--related", action="store_true", help="1-hopの関連Memoryも表示する")
    p_search.add_argument("--related-limit", type=int, default=retrieval.DEFAULT_RELATED_LIMIT)
    p_search.add_argument("-v", "--verbose", action="store_true", help="本文の抜粋も表示する")
    p_search.set_defaults(func=_cmd_search)

    p_timeline = sub.add_parser("timeline", help="event_dateでMemoryを一覧する")
    p_timeline.add_argument("--from", dest="from_date", help="開始日 (YYYY-MM-DD、境界を含む)")
    p_timeline.add_argument("--to", dest="to_date", help="終了日 (YYYY-MM-DD、境界を含む)")
    p_timeline.add_argument("--limit", type=int, default=100)
    p_timeline.add_argument("-v", "--verbose", action="store_true", help="本文の抜粋も表示する")
    p_timeline.set_defaults(func=_cmd_timeline)

    p_reindex = sub.add_parser("reindex", help="SQLite indexをVaultのMarkdownから作り直す")
    p_reindex.set_defaults(func=_cmd_reindex)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
