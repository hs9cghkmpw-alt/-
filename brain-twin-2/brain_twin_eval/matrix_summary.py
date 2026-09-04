"""Summarize PA1 open-benchmark reports and select the next development candidate.

This module is evaluation-only. It never reads a user Vault and must not be used as a
formal blind-acceptance decision. The committed v2 benchmark has open judgements.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class MatrixEntry:
    candidate_id: str
    kind: str
    model_name: str
    model_revision: str
    instruction_id: str
    dimension: int
    backend_label: str
    base_candidate_id: str | None
    recall_at_5: float
    mrr_at_10: float
    ndcg_at_10: float
    must_hit_at_5: float | None
    false_positive_at_5: float
    warm_p95_seconds: float | None
    warm_rank_drift_count: int
    reproducible: bool
    selection_eligible: bool
    report_path: str

    def __post_init__(self) -> None:
        # Validate at the value-object boundary too: callers may construct entries
        # directly instead of going through the JSON report parser.
        drift = self.warm_rank_drift_count
        if isinstance(drift, bool) or not isinstance(drift, int) or drift < 0:
            raise MatrixSummaryError("warm_rank_drift_count must be a non-negative integer")
        _boolean(self.reproducible, field="reproducible")
        _boolean(self.selection_eligible, field="selection_eligible")
        if self.reproducible != (drift == 0):
            raise MatrixSummaryError("reproducible does not match warm ranking drift")
        if self.selection_eligible and not self.reproducible:
            raise MatrixSummaryError("non-reproducible report cannot be selection eligible")
        for field in ("recall_at_5", "mrr_at_10", "ndcg_at_10", "false_positive_at_5"):
            _number(getattr(self, field), field=field)
        if self.must_hit_at_5 is not None:
            _number(self.must_hit_at_5, field="must_hit_at_5")
        if self.warm_p95_seconds is not None:
            _number(self.warm_p95_seconds, field="warm.p95_seconds", upper=None)


class MatrixSummaryError(ValueError):
    pass


def _number(value: Any, *, field: str, upper: float | None = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MatrixSummaryError(f"{field} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise MatrixSummaryError(f"{field} must be finite") from exc
    if not math.isfinite(result) or result < 0 or (upper is not None and result > upper):
        bounds = "non-negative" if upper is None else f"between 0 and {upper}"
        raise MatrixSummaryError(f"{field} must be finite and {bounds}")
    return result


def _boolean(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise MatrixSummaryError(f"{field} must be boolean")
    return value


def entry_from_payload(payload: Mapping[str, Any], *, report_path: str) -> MatrixEntry:
    try:
        manifest = payload["manifest"]
        overall = payload["overall"]
        latency = payload["latency"]
        backend_label = str(manifest["backend_label"])
        backend_params = manifest.get("backend_params") or {}
        recall = overall["recall_at"]
    except (KeyError, TypeError) as exc:
        raise MatrixSummaryError(f"malformed evaluation report: {report_path}") from exc

    dimension = manifest.get("dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
        raise MatrixSummaryError(f"invalid dimension in {report_path}")

    must_hit_raw = overall.get("must_hit_at_5")
    must_hit = None if must_hit_raw is None else _number(must_hit_raw, field="must_hit_at_5")
    warm_p95_raw = (latency.get("warm") or {}).get("p95_seconds")
    warm_p95 = None if warm_p95_raw is None else _number(warm_p95_raw, field="warm.p95_seconds", upper=None)
    drift = latency.get("warm_rank_drift_count")
    reproducible = payload.get("reproducible")
    selection_eligible = payload.get("selection_eligible")
    kind = "reranked" if backend_label == "evaluation_rerank" else "dense"

    return MatrixEntry(
        candidate_id=str(manifest["experiment_id"]),
        kind=kind,
        model_name=str(manifest["model_name"]),
        model_revision=str(manifest["model_revision"]),
        instruction_id=str(manifest["instruction_id"]),
        dimension=dimension,
        backend_label=backend_label,
        base_candidate_id=(
            str(backend_params["base_candidate_id"])
            if backend_params.get("base_candidate_id")
            else None
        ),
        recall_at_5=_number(recall["5"], field="recall_at.5"),
        mrr_at_10=_number(overall["mrr_at_10"], field="mrr_at_10"),
        ndcg_at_10=_number(overall["ndcg_at_10"], field="ndcg_at_10"),
        must_hit_at_5=must_hit,
        false_positive_at_5=_number(overall["false_positive_at_5"], field="false_positive_at_5"),
        warm_p95_seconds=warm_p95,
        warm_rank_drift_count=drift,
        reproducible=reproducible,
        selection_eligible=selection_eligible,
        report_path=report_path,
    )


def _quality_key(entry: MatrixEntry) -> tuple[float, ...]:
    """Deterministic open-dev ordering; quality first, latency only as late tie-break."""
    must_hit = -1.0 if entry.must_hit_at_5 is None else entry.must_hit_at_5
    latency = float("inf") if entry.warm_p95_seconds is None else entry.warm_p95_seconds
    return (
        entry.ndcg_at_10,
        must_hit,
        entry.mrr_at_10,
        entry.recall_at_5,
        -entry.false_positive_at_5,
        -latency,
    )


def choose_winner(entries: Iterable[MatrixEntry], *, kind: str | None = None) -> MatrixEntry | None:
    selected = [
        entry
        for entry in entries
        if entry.selection_eligible and (kind is None or entry.kind == kind)
    ]
    if not selected:
        return None
    return max(selected, key=lambda entry: (_quality_key(entry), entry.candidate_id))


def summarize_payloads(items: Iterable[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    entries: list[MatrixEntry] = []
    dataset_sha: str | None = None
    dataset_version: str | None = None
    split: str | None = None
    judgement_visibility: str | None = None
    git_commit: str | None = None

    for path, payload in items:
        current_sha = str(payload.get("dataset_sha256", ""))
        current_version = str(payload.get("dataset_version", ""))
        current_split = payload.get("split")
        current_visibility = str(payload.get("judgement_visibility", ""))
        manifest = payload.get("manifest")
        if not isinstance(manifest, Mapping):
            raise MatrixSummaryError(f"report lacks manifest: {path}")
        current_commit = str(manifest.get("git_commit", ""))
        if not current_sha or not current_version or not current_commit:
            raise MatrixSummaryError(f"report lacks dataset/Git identity: {path}")
        if dataset_sha is None:
            dataset_sha = current_sha
            dataset_version = current_version
            split = current_split
            judgement_visibility = current_visibility
            git_commit = current_commit
        elif (
            current_sha != dataset_sha
            or current_version != dataset_version
            or current_split != split
            or current_visibility != judgement_visibility
            or current_commit != git_commit
        ):
            raise MatrixSummaryError(
                "all matrix reports must use the same dataset/split/judgement visibility/Git commit"
            )
        entries.append(entry_from_payload(payload, report_path=path))

    if not entries:
        raise MatrixSummaryError("no evaluation reports found")

    candidate_ids = [entry.candidate_id for entry in entries]
    duplicates = sorted({candidate_id for candidate_id in candidate_ids if candidate_ids.count(candidate_id) > 1})
    if duplicates:
        raise MatrixSummaryError(
            "duplicate candidate IDs in matrix reports: " + ", ".join(duplicates)
        )

    entries.sort(key=lambda entry: entry.candidate_id)
    dense_winner = choose_winner(entries, kind="dense")
    overall_winner = choose_winner(entries)
    return {
        "schema": 1,
        "decision_scope": "open-development-only",
        "formal_blind_acceptance": False,
        "warning": "Open judgements may be used for iteration but not final production acceptance.",
        "dataset_version": dataset_version,
        "dataset_sha256": dataset_sha,
        "git_commit": git_commit,
        "split": split,
        "judgement_visibility": judgement_visibility,
        "entry_count": len(entries),
        "selection_eligible_entry_count": sum(
            1 for entry in entries if entry.selection_eligible
        ),
        "selection_ineligible_candidates": [
            entry.candidate_id for entry in entries if not entry.selection_eligible
        ],
        "entries": [asdict(entry) for entry in entries],
        "dense_winner": asdict(dense_winner) if dense_winner else None,
        "overall_open_winner": asdict(overall_winner) if overall_winner else None,
        "selection_order": [
            "nDCG@10",
            "must-hit@5",
            "MRR@10",
            "Recall@5",
            "lower false-positive@5",
            "lower warm p95 latency",
            "candidate_id deterministic tie-break",
        ],
    }


def collect_reports(root: Path) -> list[tuple[str, Mapping[str, Any]]]:
    paths = sorted(
        set(root.rglob("dense_report.json")) | set(root.rglob("reranked_report.json")),
        key=lambda path: path.as_posix(),
    )
    items: list[tuple[str, Mapping[str, Any]]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise MatrixSummaryError(f"report root must be an object: {path}")
        items.append((path.relative_to(root).as_posix(), payload))
    return items


def summary_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# PA1 Open Matrix Summary",
        "",
        "> Development evidence only. The committed open benchmark is not formal blind acceptance.",
        "",
        f"- Dataset: `{summary['dataset_version']}` (`{summary['dataset_sha256']}`)",
        f"- Git commit: `{summary['git_commit']}`",
        f"- Split: `{summary['split']}`",
        f"- Reports: {summary['entry_count']}",
        "",
        "| Candidate | Kind | Eligible | Reproducible | Model | Instruction | Dim | Recall@5 | MRR@10 | nDCG@10 | must-hit@5 | FP@5 | warm p95 |",
        "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for entry in summary["entries"]:
        must_hit = "n/a" if entry["must_hit_at_5"] is None else f"{entry['must_hit_at_5']:.4f}"
        warm = "n/a" if entry["warm_p95_seconds"] is None else f"{entry['warm_p95_seconds']:.4f}s"
        lines.append(
            f"| `{entry['candidate_id']}` | {entry['kind']} | {entry['selection_eligible']} | {entry['reproducible']} | `{entry['model_name']}` | `{entry['instruction_id']}` | "
            f"{entry['dimension']} | {entry['recall_at_5']:.4f} | {entry['mrr_at_10']:.4f} | "
            f"{entry['ndcg_at_10']:.4f} | {must_hit} | {entry['false_positive_at_5']:.4f} | {warm} |"
        )

    dense = summary.get("dense_winner")
    overall = summary.get("overall_open_winner")
    lines.extend(["", "## Open-development selection", ""])
    lines.append("- Dense winner: " + (f"`{dense['candidate_id']}`" if dense else "n/a"))
    lines.append("- Overall open winner: " + (f"`{overall['candidate_id']}`" if overall else "n/a"))
    lines.extend(
        [
            "",
            "Selection priority is nDCG@10, must-hit@5, MRR@10, Recall@5, lower FP@5, then lower warm p95.",
            "Reports with ranking drift are retained for diagnosis but excluded from every winner selection.",
            "A genuine held-out set and Windows acceptance budgets remain required before production selection.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    summary = summarize_payloads(collect_reports(args.root))
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    args.out_md.write_text(summary_markdown(summary), encoding="utf-8")
    print(f"dense winner: {summary['dense_winner']['candidate_id'] if summary['dense_winner'] else 'n/a'}")
    print(f"overall open winner: {summary['overall_open_winner']['candidate_id'] if summary['overall_open_winner'] else 'n/a'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
