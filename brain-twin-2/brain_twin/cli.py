"""CLIエントリポイント(指示書29・35・37章)。"""
from __future__ import annotations

import argparse
import sys

from brain_twin import db, embedding_runtime, hybrid_search, pipeline, retrieval, search, vector_search
from brain_twin.config import load_config
from brain_twin.embedding_config import default_user_config_path, load_embedding_settings
from brain_twin.embedding_provider import EmbeddingConfigurationError, EmbeddingError
from brain_twin.embedding_service import EmbeddingService, inspect_embedding_status


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


def _print_vector_results(results: list[vector_search.VectorResult], *, verbose: bool) -> None:
    if not results:
        print("該当するMemoryが見つかりませんでした。")
        return
    for r in results:
        topics = ",".join(r.topics) if r.topics else "-"
        entities = ",".join(r.entities) if r.entities else "-"
        print(f"[{r.event_date}] ({r.type} / importance={r.importance} / confidence={r.confidence:.2f} / topics={topics} / entities={entities})")
        print(f"  {r.title}")
        if verbose:
            snippet = r.content if len(r.content) <= 120 else r.content[:120] + "…"
            print(f"  {snippet}")
            print(f"  similarity={r.similarity:.4f} vector_rank={r.vector_rank}")
        print(f"  id={r.memory_id}")
        print()


def _print_hybrid_results(results: list[hybrid_search.HybridResult], *, verbose: bool) -> None:
    if not results:
        print("該当するMemoryが見つかりませんでした。")
        return
    for r in results:
        topics = ",".join(r.topics) if r.topics else "-"
        entities = ",".join(r.entities) if r.entities else "-"
        print(f"[{r.event_date}] ({r.type} / importance={r.importance} / confidence={r.confidence:.2f} / topics={topics} / entities={entities})")
        print(f"  {r.title}")
        if verbose:
            snippet = r.content if len(r.content) <= 120 else r.content[:120] + "…"
            print(f"  {snippet}")
            lexical = (
                f"lexical_rank={r.lexical_rank} raw={r.lexical_raw_score:.4f}"
                if r.lexical_rank is not None else "lexical=-"
            )
            vector = (
                f"vector_rank={r.vector_rank} similarity={r.vector_similarity:.4f}"
                if r.vector_rank is not None else "vector=-"
            )
            print(
                f"  {lexical} / {vector} / fusion={r.fusion_score:.4f} / "
                f"metadata_multiplier={r.metadata_multiplier:.4f} / final={r.final_score:.4f}"
            )
        print(f"  id={r.memory_id}")
        print()


def _print_related(related: list[retrieval.RelatedMemory], *, verbose: bool) -> None:
    if not related:
        return
    print("関連Memory:")
    for item in related:
        print(f"[{item.event_date}] ({item.type}) {item.title}")
        print(f"  id={item.memory_id}")
        for relation in item.relations:
            print(
                f"  <- {relation.primary_memory_id} "
                f"({relation.direction} / {relation.relation_type} / "
                f"strength={relation.strength:.3f}): {relation.reason}"
            )
        if verbose:
            snippet = item.content if len(item.content) <= 120 else item.content[:120] + "…"
            print(f"  {snippet}")
        print()


def _cmd_search(args: argparse.Namespace) -> int:
    config = load_config()

    # Sprint 4D CLI hardening: validate --related-limit before starting any embedding
    # config/provider/search work (plain, --vector, and --hybrid alike), so a negative
    # --related-limit fails fast with nothing printed and no provider/vector search call.
    if args.related and args.related_limit < 0:
        print("[NG] --related-limit must be non-negative", file=sys.stderr)
        return 1

    if args.vector or args.hybrid:
        try:
            settings, backend, provider = _embedding_components(require_provider=True)
        except (EmbeddingError, OSError, ValueError) as exc:
            print(f"[NG] Vector search: {exc}", file=sys.stderr)
            return 1
        try:
            with db.connect(config) as conn:
                if args.vector:
                    primary_results = vector_search.vector_search(
                        conn, args.query, provider, backend, limit=args.limit
                    )
                    _print_vector_results(primary_results, verbose=args.verbose)
                else:
                    primary_results = hybrid_search.hybrid_search(
                        conn, args.query, provider, backend, limit=args.limit
                    )
                    _print_hybrid_results(primary_results, verbose=args.verbose)

                if args.related:
                    retrieval_result = retrieval.retrieve_from_primary(
                        conn, primary_results, related_limit=args.related_limit
                    )
                    _print_related(retrieval_result.related, verbose=args.verbose)
        except EmbeddingError as exc:
            print(f"[NG] Vector search: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"[NG] {exc}", file=sys.stderr)
            return 1
        return 0

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
    if retrieval_result is not None:
        _print_related(retrieval_result.related, verbose=args.verbose)
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


def _embedding_components(*, require_provider: bool):
    settings = load_embedding_settings(default_user_config_path())
    backend = embedding_runtime.create_backend(settings)
    provider = embedding_runtime.create_provider(settings) if require_provider else None
    if provider is not None and provider.profile.fingerprint != settings.profile.fingerprint:
        raise EmbeddingConfigurationError(
            "configured embedding profile does not match the provider profile"
        )
    return settings, backend, provider


def _print_embedding_status(status) -> None:
    print("Embeddings")
    print(f"Profile: {status.profile_fingerprint}")
    print(f"Backend: {status.backend}")
    print(f"Total active Memories: {status.total_active}")
    print(f"Ready: {status.ready}")
    print(f"Missing: {status.missing}")
    print(f"Stale: {status.stale}")
    print(f"Active profile matches config: {'yes' if status.active_matches_config else 'no'}")


def _cmd_embeddings(args: argparse.Namespace) -> int:
    config = load_config()
    try:
        require_provider = args.embeddings_command in {"sync", "rebuild"}
        settings, backend, provider = _embedding_components(require_provider=require_provider)
        if args.embeddings_command == "status":
            with db.connect(config) as conn:
                status = inspect_embedding_status(conn, settings.profile, backend.backend_id)
            _print_embedding_status(status)
            return 0
        service = EmbeddingService(config, provider, backend)
        result = service.sync() if args.embeddings_command == "sync" else service.rebuild()
        print(f"Embedded: {result.embedded}")
        print(f"Skipped: {result.skipped}")
        print(f"Failed: {result.failed}")
        return 0
    except (EmbeddingError, OSError, ValueError) as exc:
        print(f"[NG] Embeddings: {exc}", file=sys.stderr)
        return 1


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
    p_search.add_argument(
        "--related", action="store_true",
        help="1-hopの関連Memoryも表示する(--vector/--hybridとも併用可、Sprint 4D)",
    )
    p_search.add_argument("--related-limit", type=int, default=retrieval.DEFAULT_RELATED_LIMIT)
    vector_group = p_search.add_mutually_exclusive_group()
    vector_group.add_argument("--vector", action="store_true", help="Vector Primary Searchを使う(Sprint 4C)")
    vector_group.add_argument("--hybrid", action="store_true", help="lexical+VectorのHybrid Primary Searchを使う(Sprint 4C)")
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

    p_embeddings = sub.add_parser("embeddings", help="embedding cacheを明示的に管理する")
    embeddings_sub = p_embeddings.add_subparsers(dest="embeddings_command", required=True)
    for command in ("status", "sync", "rebuild"):
        child = embeddings_sub.add_parser(command)
        child.set_defaults(func=_cmd_embeddings)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
