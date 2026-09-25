from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.advanced import AdvancedSpec
from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec


BUILD_IMPLEMENTATION = "m8-72-contextual-anomaly-v1"


@dataclass(slots=True)
class FrequencyRobustEncoder:
    categorical_features: tuple[str, ...]
    numeric_features: tuple[str, ...]
    category_frequency: dict[str, dict[str, float]]
    numeric_median: dict[str, float]
    numeric_scale: dict[str, float]

    @classmethod
    def fit(
        cls,
        frame: pd.DataFrame,
        *,
        categorical_features: tuple[str, ...],
        numeric_features: tuple[str, ...],
    ) -> "FrequencyRobustEncoder":
        category_frequency: dict[str, dict[str, float]] = {}
        for column in categorical_features:
            values = frame[column].fillna("__MISSING__").astype(str)
            frequencies = values.value_counts(normalize=True, dropna=False)
            category_frequency[column] = {
                str(key): float(value) for key, value in frequencies.items()
            }

        numeric_median: dict[str, float] = {}
        numeric_scale: dict[str, float] = {}
        for column in numeric_features:
            # pandas preserves bool dtype through to_numeric(). NumPy quantile
            # interpolation then attempts boolean subtraction and fails. Treat
            # boolean/nullable-boolean flags as the numeric 0/1 features they
            # semantically are before computing robust statistics.
            values = (
                pd.to_numeric(frame[column], errors="coerce")
                .astype("float64")
                .replace([np.inf, -np.inf], np.nan)
            )
            median = float(values.median()) if values.notna().any() else 0.0
            q1 = float(values.quantile(0.25)) if values.notna().any() else median
            q3 = float(values.quantile(0.75)) if values.notna().any() else median
            scale = q3 - q1
            if not math.isfinite(scale) or scale <= 1e-12:
                std = float(values.std()) if values.notna().sum() > 1 else 1.0
                scale = std if math.isfinite(std) and std > 1e-12 else 1.0
            numeric_median[column] = median
            numeric_scale[column] = scale

        return cls(
            categorical_features=categorical_features,
            numeric_features=numeric_features,
            category_frequency=category_frequency,
            numeric_median=numeric_median,
            numeric_scale=numeric_scale,
        )

    def transform(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        blocks: list[np.ndarray] = []
        rarity_blocks: list[np.ndarray] = []
        for column in self.categorical_features:
            values = frame[column].fillna("__MISSING__").astype(str)
            frequency = (
                values.map(self.category_frequency[column])
                .fillna(0.0)
                .to_numpy(dtype=float)
            )
            rarity = -np.log10(np.clip(frequency, 1e-8, 1.0))
            blocks.append(rarity.reshape(-1, 1))
            rarity_blocks.append(rarity)
        for column in self.numeric_features:
            values = (
                pd.to_numeric(frame[column], errors="coerce")
                .astype("float64")
                .to_numpy(dtype=float)
            )
            median = self.numeric_median[column]
            values = np.where(np.isfinite(values), values, median)
            robust = np.clip((values - median) / self.numeric_scale[column], -25.0, 25.0)
            blocks.append(robust.reshape(-1, 1))

        matrix = np.hstack(blocks) if blocks else np.empty((len(frame), 0), dtype=float)
        rarity_mean = (
            np.mean(np.column_stack(rarity_blocks), axis=1)
            if rarity_blocks
            else np.zeros(len(frame), dtype=float)
        )
        return matrix.astype(np.float32, copy=False), rarity_mean.astype(np.float32, copy=False)


@dataclass(slots=True)
class AnomalyBundle:
    encoder: FrequencyRobustEncoder
    model: IsolationForest
    train_raw_scores_sorted: np.ndarray
    fitted_split: str
    schema_version: str

    def score(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        matrix, rarity = self.encoder.transform(frame)
        raw = -self.model.decision_function(matrix)
        rank = np.searchsorted(self.train_raw_scores_sorted, raw, side="right")
        percentile = rank / max(1, len(self.train_raw_scores_sorted))
        return raw.astype(np.float32), percentile.astype(np.float32), rarity


@dataclass(frozen=True, slots=True)
class AnomalyFeaturesResult:
    artifact: Path
    model_artifact: Path
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_stage(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def advanced_feature_columns(columns: list[str]) -> list[str]:
    return [c for c in columns if c.startswith("semantic_") or c.startswith("graph_")]


def build_anomaly_features(
    *,
    root: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    advanced_spec: AdvancedSpec,
) -> AnomalyFeaturesResult:
    from argos.common.duckdb import connect
    from argos.gold.utils import columns_of, copy_query, parquet_source

    base_path = root / modeling_spec.model_matrix
    semantic_path = root / advanced_spec.artifacts.semantic_features
    graph_path = root / advanced_spec.artifacts.graph_features
    for path in [base_path, semantic_path, graph_path]:
        if not path.exists():
            raise FileNotFoundError(f"M8 anomaly stage requires {path}")

    cache_path = root / ".cache" / "m8" / "pre_anomaly.parquet"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        base = parquet_source(base_path)
        semantic = parquet_source(semantic_path)
        graph = parquet_source(graph_path)
        semantic_cols = [c for c in columns_of(con, semantic) if c.startswith("semantic_")]
        graph_cols = [c for c in columns_of(con, graph) if c.startswith("graph_")]
        projection = [
            "b.*",
            *(f's."{c}" AS "{c}"' for c in semantic_cols),
            *(f'g."{c}" AS "{c}"' for c in graph_cols),
        ]
        split_literals = ",".join(f"'{v}'" for v in advanced_spec.governance.development_splits)
        copy_query(
            con,
            f"""
            SELECT {', '.join(projection)}
            FROM {base} b
            JOIN {semantic} s USING (contract_id, t0, split)
            JOIN {graph} g USING (contract_id, t0, split)
            WHERE b.split IN ({split_literals})
            """,
            cache_path,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=True,
        )
        merged = parquet_source(cache_path)
        columns = columns_of(con, merged)
        categorical = tuple(
            c for c in gold_spec.contract_features.categorical_candidates if c in columns
        )
        excluded = {
            modeling_spec.id_column,
            modeling_spec.t0_column,
            modeling_spec.split_column,
            modeling_spec.target,
            *categorical,
        }
        numeric = tuple(c for c in columns if c not in excluded and not c.startswith("_"))
        if not categorical and not numeric:
            raise ValueError("M8 anomaly stage found no usable features")
        feature_list = [*categorical, *numeric]
        quoted_features = ", ".join(f'"{c}"' for c in feature_list)
        sample = con.execute(
            f"""
            SELECT {modeling_spec.id_column}, {quoted_features}
            FROM {merged}
            WHERE {modeling_spec.split_column} = 'train'
            ORDER BY hash(
                CAST({modeling_spec.id_column} AS VARCHAR)
                || '::{advanced_spec.anomaly.random_seed}'
            )
            LIMIT {advanced_spec.anomaly.max_train_rows}
            """
        ).fetchdf()
        split_counts = con.execute(
            (
                f"SELECT {modeling_spec.split_column} AS split, COUNT(*) AS rows "
                f"FROM {merged} GROUP BY 1"
            )
        ).fetchdf()
    finally:
        con.close()

    encoder = FrequencyRobustEncoder.fit(
        sample,
        categorical_features=categorical,
        numeric_features=numeric,
    )
    train_matrix, _ = encoder.transform(sample)
    max_samples = min(advanced_spec.anomaly.max_samples, len(sample))
    model = IsolationForest(
        n_estimators=advanced_spec.anomaly.n_estimators,
        max_samples=max_samples,
        contamination=advanced_spec.anomaly.contamination,
        random_state=advanced_spec.anomaly.random_seed,
        n_jobs=-1,
    )
    model.fit(train_matrix)
    train_raw_scores = -model.decision_function(train_matrix)
    bundle = AnomalyBundle(
        encoder=encoder,
        model=model,
        train_raw_scores_sorted=np.sort(train_raw_scores.astype(np.float32)),
        fitted_split="train",
        schema_version=advanced_spec.schema_version,
    )

    model_artifact = root / advanced_spec.artifacts.anomaly_model
    model_artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_artifact, compress=3)

    import pyarrow as pa
    import pyarrow.parquet as pq

    artifact = root / advanced_spec.artifacts.anomaly_features
    artifact.parent.mkdir(parents=True, exist_ok=True)
    if artifact.exists():
        artifact.unlink()
    parquet_file = pq.ParquetFile(cache_path)
    writer: pq.ParquetWriter | None = None
    rows_written = 0
    score_min = math.inf
    score_max = -math.inf
    requested_columns = [
        modeling_spec.id_column,
        modeling_spec.t0_column,
        modeling_spec.split_column,
        *categorical,
        *numeric,
    ]
    try:
        for batch in parquet_file.iter_batches(
            batch_size=modeling_spec.batch_size,
            columns=requested_columns,
        ):
            frame = batch.to_pandas()
            raw_score, percentile, rarity = bundle.score(frame)
            output = pd.DataFrame(
                {
                    "contract_id": frame[modeling_spec.id_column].astype(str),
                    "t0": pd.to_datetime(frame[modeling_spec.t0_column], errors="raise"),
                    "split": frame[modeling_spec.split_column].astype(str),
                    "anomaly_isolation_raw_score": raw_score,
                    "anomaly_score": percentile,
                    "anomaly_categorical_rarity_mean": rarity,
                    "_anomaly_model_fit_split": "train",
                    "_m8_schema_version": advanced_spec.schema_version,
                }
            )
            score_min = min(score_min, float(np.min(percentile)))
            score_max = max(score_max, float(np.max(percentile)))
            table = pa.Table.from_pandas(output, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(artifact, table.schema, compression="zstd")
            writer.write_table(table)
            rows_written += len(output)
    finally:
        if writer is not None:
            writer.close()

    observed_splits = sorted(split_counts["split"].astype(str).tolist())
    expected_rows = int(split_counts["rows"].sum())
    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="anomaly_train_only_fit",
        category="evaluation_governance",
        passed=bundle.fitted_split == "train",
        observed={"fitted_split": bundle.fitted_split, "sample_rows": len(sample)},
        requirement="anomaly detector is fit only on TRAIN and frozen before VALIDATION scoring",
    )
    add_validation(
        records,
        check_id="anomaly_rows_aligned",
        category="grain",
        passed=rows_written == expected_rows,
        observed={"expected_rows": expected_rows, "written_rows": rows_written},
        requirement="one anomaly score row per M8 development contract",
    )
    add_validation(
        records,
        check_id="anomaly_score_range",
        category="quality",
        passed=0.0 <= score_min <= score_max <= 1.0,
        observed={"min": score_min, "max": score_max},
        requirement="anomaly_score is a TRAIN-reference empirical percentile in [0,1]",
    )
    add_validation(
        records,
        check_id="anomaly_holdouts_isolated",
        category="evaluation_governance",
        passed=set(observed_splits).issubset(set(advanced_spec.governance.development_splits)),
        observed={"splits": observed_splits},
        requirement="M8 anomaly development consumes only TRAIN/VALIDATION",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "advanced" / "72_validation.parquet")

    manifest_path = root / advanced_spec.artifacts.anomaly_manifest
    write_manifest(
        manifest_path,
        {
            "schema_version": advanced_spec.schema_version,
            "implementation": BUILD_IMPLEMENTATION,
            "artifact": str(artifact.relative_to(root)),
            "model_artifact": str(model_artifact.relative_to(root)),
            "fitted_split": bundle.fitted_split,
            "train_sample_rows": len(sample),
            "rows_scored": rows_written,
            "categorical_features": list(categorical),
            "numeric_features": list(numeric),
            "consumed_test_or_oot_for_selection": False,
        },
    )
    return AnomalyFeaturesResult(
        artifact=artifact,
        model_artifact=model_artifact,
        validation=validation,
        manifest_path=manifest_path,
    )
