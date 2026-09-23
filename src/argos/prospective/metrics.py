from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

METRICS_IMPLEMENTATION = "m7-63-prospective-metrics-v2"


def expected_calibration_error(y_true: np.ndarray, score: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    bucket = np.clip(np.digitize(score, edges[1:-1], right=True), 0, bins - 1)
    ece = 0.0
    for idx in range(bins):
        mask = bucket == idx
        if not mask.any():
            continue
        ece += mask.mean() * abs(float(y_true[mask].mean()) - float(score[mask].mean()))
    return float(ece)


def _ranked(
    frame: pd.DataFrame,
    *,
    score: str,
    raw_score: str | None,
    id_column: str | None,
) -> pd.DataFrame:
    cols = [score]
    ascending = [False]
    if raw_score is not None:
        cols.append(raw_score)
        ascending.append(False)
    if id_column is not None:
        cols.append(id_column)
        ascending.append(True)
    return frame.sort_values(cols, ascending=ascending, kind="mergesort")


def prospective_metrics(
    frame: pd.DataFrame,
    *,
    label: str,
    score: str,
    fraction: float,
    raw_score: str | None = None,
    id_column: str | None = None,
) -> dict[str, float]:
    required = [label, score]
    if raw_score is not None:
        required.append(raw_score)
    if id_column is not None:
        required.append(id_column)
    clean = frame[required].dropna().copy()
    if clean.empty or clean[label].nunique() < 2:
        raise ValueError("Prospective metrics require non-empty matured labels with both classes")
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")

    y = clean[label].astype(int).to_numpy()
    s = clean[score].astype(float).to_numpy()
    if not np.isfinite(s).all():
        raise ValueError("prospective scores must be finite")
    if ((s < 0) | (s > 1)).any():
        raise ValueError("calibrated prospective scores must lie in [0, 1]")

    prevalence = float(y.mean())
    k = max(1, math.ceil(len(clean) * fraction))
    ranked = _ranked(clean, score=score, raw_score=raw_score, id_column=id_column)
    top = ranked[label].astype(int).to_numpy()[:k]
    precision_k = float(top.mean())
    recall_k = float(top.sum() / y.sum()) if y.sum() else float("nan")
    lift_k = float(precision_k / prevalence) if prevalence > 0 else float("nan")
    pr_auc = float(average_precision_score(y, s))
    brier = float(brier_score_loss(y, s))
    prevalence_baseline = np.full(len(y), prevalence, dtype=float)
    brier_baseline = float(brier_score_loss(y, prevalence_baseline))
    eps = np.finfo(float).eps
    clipped = np.clip(s, eps, 1 - eps)

    return {
        "rows": float(len(clean)),
        "positives": float(y.sum()),
        "prevalence": prevalence,
        "pr_auc": pr_auc,
        "pr_auc_over_prevalence": pr_auc / prevalence if prevalence > 0 else float("nan"),
        "roc_auc": float(roc_auc_score(y, s)),
        "log_loss": float(log_loss(y, clipped, labels=[0, 1])),
        "brier": brier,
        "brier_prevalence_baseline": brier_baseline,
        "brier_relative_to_prevalence_baseline": brier / brier_baseline if brier_baseline > 0 else float("nan"),
        "ece": expected_calibration_error(y, s),
        "precision_at_k": precision_k,
        "recall_at_k": recall_k,
        "lift_at_k": lift_k,
        "k_rows": float(k),
    }


def block_bootstrap_metrics(
    frame: pd.DataFrame,
    *,
    block_column: str,
    label: str,
    score: str,
    fraction: float,
    raw_score: str | None,
    id_column: str | None,
    replicates: int,
    confidence_level: float,
    seed: int = 20260923,
    metric_names: Iterable[str] = ("pr_auc", "lift_at_k", "brier", "ece"),
) -> pd.DataFrame:
    if block_column not in frame.columns:
        raise ValueError(f"missing bootstrap block column: {block_column}")
    blocks = frame[block_column].dropna().astype(str).unique()
    if len(blocks) < 2:
        raise ValueError("block bootstrap requires at least two independent time blocks")
    rng = np.random.default_rng(seed)
    values: dict[str, list[float]] = {name: [] for name in metric_names}

    grouped = {str(k): v for k, v in frame.groupby(frame[block_column].astype(str), sort=False)}
    for _ in range(replicates):
        sampled = rng.choice(blocks, size=len(blocks), replace=True)
        parts = [grouped[str(block)].copy() for block in sampled]
        sample = pd.concat(parts, ignore_index=True)
        try:
            metrics = prospective_metrics(
                sample,
                label=label,
                score=score,
                fraction=fraction,
                raw_score=raw_score,
                id_column=id_column,
            )
        except ValueError:
            continue
        for name in values:
            values[name].append(float(metrics[name]))

    alpha = (1.0 - confidence_level) / 2.0
    rows: list[dict[str, float | str | int]] = []
    for name, observed in values.items():
        arr = np.asarray(observed, dtype=float)
        arr = arr[np.isfinite(arr)]
        if len(arr) == 0:
            continue
        rows.append(
            {
                "metric": name,
                "replicates_requested": int(replicates),
                "replicates_valid": int(len(arr)),
                "ci_lower": float(np.quantile(arr, alpha)),
                "ci_median": float(np.quantile(arr, 0.5)),
                "ci_upper": float(np.quantile(arr, 1.0 - alpha)),
                "confidence_level": float(confidence_level),
                "time_blocks": int(len(blocks)),
            }
        )
    return pd.DataFrame.from_records(rows)
