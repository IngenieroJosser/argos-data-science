from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Iterator

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec
from argos.models.data import FeatureContract, load_feature_contract, resolve_project_path
from argos.models.metrics import probability_metrics


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_frozen_v1(root: Path) -> tuple[object, object, dict]:
    model_dir = root / "artifacts" / "models" / "m4"
    selection_path = model_dir / "selected_model.json"
    if not selection_path.exists():
        raise FileNotFoundError(selection_path)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection.get("status") != "FROZEN_FOR_TEST":
        raise ValueError("ARGOS V1 selection is not frozen")
    model_path = root / str(selection["model_artifact"])
    calibrator_path = root / str(selection["calibrator_artifact"])
    if not model_path.exists() or not calibrator_path.exists():
        raise FileNotFoundError("Frozen M4 model/calibrator artifact is missing")
    observed_model_hash = sha256_file(model_path)
    observed_calibrator_hash = sha256_file(calibrator_path)
    if observed_model_hash != str(selection["model_sha256"]):
        raise ValueError("Frozen M4 model hash mismatch")
    if observed_calibrator_hash != str(selection["calibrator_sha256"]):
        raise ValueError("Frozen M4 calibrator hash mismatch")
    return joblib.load(model_path), joblib.load(calibrator_path), selection


def iter_time_batches(
    parquet_path: Path,
    *,
    columns: Iterable[str],
    t0_column: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    batch_size: int,
) -> Iterator[pd.DataFrame]:
    requested = list(dict.fromkeys([*columns, t0_column]))
    pf = pq.ParquetFile(parquet_path)
    for batch in pf.iter_batches(batch_size=batch_size, columns=requested):
        frame = batch.to_pandas()
        t0 = pd.to_datetime(frame[t0_column], errors="coerce")
        mask = t0.notna()
        if start is not None:
            mask &= t0 >= start
        if end is not None:
            mask &= t0 <= end
        frame = frame.loc[mask].copy()
        if frame.empty:
            continue
        frame[t0_column] = pd.to_datetime(frame[t0_column], errors="raise")
        yield frame


def load_time_slice(
    parquet_path: Path,
    *,
    columns: Iterable[str],
    t0_column: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    batch_size: int,
) -> pd.DataFrame:
    parts = list(
        iter_time_batches(
            parquet_path,
            columns=columns,
            t0_column=t0_column,
            start=start,
            end=end,
            batch_size=batch_size,
        )
    )
    if not parts:
        return pd.DataFrame(columns=list(dict.fromkeys([*columns, t0_column])))
    return pd.concat(parts, ignore_index=True)


def deterministic_time_sample(
    parquet_path: Path,
    *,
    columns: Iterable[str],
    id_column: str,
    t0_column: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    max_rows: int,
    batch_size: int,
    seed: int,
) -> pd.DataFrame:
    if max_rows <= 0:
        raise ValueError("max_rows must be > 0")
    parts: list[pd.DataFrame] = []
    cols = list(dict.fromkeys([*columns, id_column, t0_column]))
    # Stable hash threshold keeps memory bounded without requiring a full count pass.
    modulus = np.uint64(1_000_003)
    # 25% is intentionally generous; final truncation is by a second stable hash.
    threshold = np.uint64(250_001)
    for frame in iter_time_batches(
        parquet_path,
        columns=cols,
        t0_column=t0_column,
        start=start,
        end=end,
        batch_size=batch_size,
    ):
        hashed = pd.util.hash_pandas_object(frame[id_column].astype(str), index=False).to_numpy(dtype=np.uint64)
        keep = ((hashed + np.uint64(seed)) % modulus) < threshold
        selected = frame.loc[keep]
        if not selected.empty:
            parts.append(selected)
        if sum(len(p) for p in parts) >= max_rows * 3:
            break
    if not parts:
        raise ValueError("Deterministic time sample returned zero rows")
    sample = pd.concat(parts, ignore_index=True)
    order_hash = pd.util.hash_pandas_object(sample[id_column].astype(str) + f"::{seed}", index=False)
    sample = sample.assign(_sample_hash=order_hash.to_numpy()).sort_values("_sample_hash").head(max_rows)
    return sample.drop(columns=["_sample_hash"]).reset_index(drop=True)


def feature_family(contract: FeatureContract, family: str) -> tuple[str, ...]:
    if family == "contract":
        return tuple(contract.contract_features)
    if family == "contract_historical":
        return tuple(dict.fromkeys([*contract.contract_features, *contract.historical_features]))
    if family == "all":
        return tuple(contract.all_features)
    raise ValueError(f"Unsupported feature family: {family}")


def subset_contract(contract: FeatureContract, features: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    selected = tuple(features)
    selected_set = set(selected)
    categorical = tuple(f for f in contract.categorical_features if f in selected_set)
    numeric = tuple(f for f in selected if f not in set(categorical))
    return categorical, numeric


def load_contract(root: Path, gold_spec: GoldSpec, modeling_spec: ModelingSpec) -> FeatureContract:
    return load_feature_contract(root, gold_spec, modeling_spec)


def matrix_path(root: Path, modeling_spec: ModelingSpec) -> Path:
    path = resolve_project_path(root, modeling_spec.model_matrix)
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def deterministic_rank(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"contract_id", "score", "raw_score"}
    missing = required - set(frame.columns)
    if missing:
        raise KeyError(f"Ranking frame missing columns: {sorted(missing)}")
    ranked = frame.sort_values(
        ["score", "raw_score", "contract_id"],
        ascending=[False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    ranked["rank"] = np.arange(1, len(ranked) + 1, dtype=np.int64)
    return ranked


def deterministic_ranking_metrics(
    frame: pd.DataFrame,
    *,
    target: str,
    review_fractions: Iterable[float],
    model_name: str,
    split: str,
) -> pd.DataFrame:
    ranked = deterministic_rank(frame)
    y = ranked[target].astype("int8").to_numpy()
    positives = int(y.sum())
    prevalence = float(y.mean()) if len(y) else math.nan
    rows: list[dict[str, float | int | str]] = []
    for fraction in review_fractions:
        k = max(1, int(math.ceil(len(y) * float(fraction))))
        captured = int(y[:k].sum())
        precision = captured / k
        recall = captured / positives if positives else math.nan
        lift = precision / prevalence if prevalence > 0 else math.nan
        rows.append(
            {
                "model": model_name,
                "split": split,
                "review_fraction": float(fraction),
                "reviewed": k,
                "captured_positives": captured,
                "precision_at_k": float(precision),
                "recall_at_k": float(recall),
                "lift_at_k": float(lift),
                "cumulative_gain": float(recall),
                "tie_break": "score_desc/raw_score_desc/contract_id_asc",
            }
        )
    return pd.DataFrame.from_records(rows)


def probability_metric_record(model: str, split: str, y: np.ndarray, p: np.ndarray, bins: int) -> dict[str, float | int | str]:
    metrics = probability_metrics(y, p, bins=bins)
    return {
        "model": model,
        "split": split,
        "rows": metrics.rows,
        "positives": metrics.positives,
        "prevalence": metrics.prevalence,
        "pr_auc": metrics.pr_auc,
        "roc_auc": metrics.roc_auc,
        "log_loss": metrics.log_loss,
        "brier": metrics.brier,
        "ece": metrics.ece,
    }
