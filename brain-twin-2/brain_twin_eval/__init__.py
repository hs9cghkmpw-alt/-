"""Model-independent Japanese retrieval evaluation harness for Brain Twin 2.0."""

from .adapters import HybridRetriever, LexicalRetriever, VectorRetriever
from .dataset import (
    DatasetValidationError,
    EvaluationDataset,
    EvaluationMemory,
    EvaluationQuery,
    dataset_sha256,
    load_dataset,
)
from .manifest import ExperimentManifest, ManifestValidationError, build_manifest
from .metrics import ann_recall_at_k
from .resources import PeakRssReading, peak_rss_reading
from .runner import (
    AnnRecallSummary,
    EvaluationRetriever,
    EvaluationRun,
    RankedResult,
    evaluate_ann_recall,
    evaluate_rankings,
    evaluate_retriever,
)
from .statistics import ConfidenceInterval, PairedMetricDelta, bootstrap_mean_ci, metric_ci95, paired_metric_delta

__all__ = [
    "AnnRecallSummary",
    "ConfidenceInterval",
    "DatasetValidationError",
    "EvaluationDataset",
    "EvaluationMemory",
    "EvaluationQuery",
    "ExperimentManifest",
    "ManifestValidationError",
    "EvaluationRetriever",
    "EvaluationRun",
    "HybridRetriever",
    "LexicalRetriever",
    "PairedMetricDelta",
    "PeakRssReading",
    "RankedResult",
    "VectorRetriever",
    "ann_recall_at_k",
    "bootstrap_mean_ci",
    "build_manifest",
    "dataset_sha256",
    "evaluate_ann_recall",
    "evaluate_rankings",
    "evaluate_retriever",
    "load_dataset",
    "metric_ci95",
    "paired_metric_delta",
    "peak_rss_reading",
]
