from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import sql_string
from argos.common.validation import add_validation, write_manifest
from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec
from argos.config.robustness import RobustnessSpec
from argos.models.boosting import fit_boosting_bundle
from argos.models.metrics import metric_frame, ranking_metrics
from argos.robustness.common import (
    deterministic_time_sample,
    iter_time_batches,
    load_contract,
    matrix_path,
)


BUILD_IMPLEMENTATION = "m5-40-rolling-origin-backtesting-v1"


@dataclass(frozen=True, slots=True)
class BacktestingResult:
    metrics: pd.DataFrame
    ranking: pd.DataFrame
    folds: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _count_period(con, source: str, t0_col: str, target: str, *, before: pd.Timestamp | None = None, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> dict[str, int]:
    clauses: list[str] = []
    if before is not None:
        clauses.append(f"{t0_col} < TIMESTAMP {sql_string(before.strftime('%Y-%m-%d %H:%M:%S'))}")
    if start is not None:
        clauses.append(f"{t0_col} >= TIMESTAMP {sql_string(start.strftime('%Y-%m-%d %H:%M:%S'))}")
    if end is not None:
        clauses.append(f"{t0_col} <= TIMESTAMP {sql_string(end.strftime('%Y-%m-%d %H:%M:%S'))}")
    where = " AND ".join(clauses) if clauses else "TRUE"
    row = con.execute(
        f"""
        SELECT COUNT(*) AS row_count,
               COUNT(*) FILTER (WHERE {target}=1) AS positives
        FROM {source}
        WHERE {where}
        """
    ).fetchone()
    return {"rows": int(row[0]), "positives": int(row[1])}


def build_temporal_backtesting(
    *,
    root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    robustness_spec: RobustnessSpec,
    reports_root: Path,
    manifest_dir: Path,
    temp_directory: Path | None = None,
) -> BacktestingResult:
    matrix = matrix_path(root, modeling_spec)
    contract = load_contract(root, gold_spec, modeling_spec)
    source = f"read_parquet({sql_string(str(matrix))})"
    con = connect(
        temp_directory=temp_directory,
        threads=robustness_spec.runtime.duckdb_threads,
        memory_limit=robustness_spec.runtime.duckdb_memory_limit,
    )
    metric_parts: list[pd.DataFrame] = []
    ranking_parts: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    try:
        for fold_index, year in enumerate(robustness_spec.backtesting.evaluation_years):
            eval_start = pd.Timestamp(year=year, month=1, day=1)
            eval_end = pd.Timestamp(year=year, month=12, day=31, hour=23, minute=59, second=59)
            train_stats = _count_period(
                con,
                source,
                modeling_spec.t0_column,
                modeling_spec.target,
                before=eval_start,
            )
            eval_stats = _count_period(
                con,
                source,
                modeling_spec.t0_column,
                modeling_spec.target,
                start=eval_start,
                end=eval_end,
            )
            if train_stats["rows"] < robustness_spec.backtesting.min_training_rows:
                raise ValueError(f"Backtest fold {year} has insufficient training rows: {train_stats}")
            if eval_stats["rows"] < robustness_spec.backtesting.min_evaluation_rows:
                raise ValueError(f"Backtest fold {year} has insufficient evaluation rows: {eval_stats}")
            if eval_stats["positives"] < robustness_spec.backtesting.min_evaluation_positives:
                raise ValueError(f"Backtest fold {year} has insufficient positives: {eval_stats}")

            sample = deterministic_time_sample(
                matrix,
                columns=[*contract.all_features, modeling_spec.target],
                id_column=modeling_spec.id_column,
                t0_column=modeling_spec.t0_column,
                start=None,
                end=eval_start - pd.Timedelta(microseconds=1),
                max_rows=robustness_spec.backtesting.max_train_rows,
                batch_size=robustness_spec.core.batch_size,
                seed=robustness_spec.core.random_seed + fold_index * 101,
            )
            y_sample = sample[modeling_spec.target].astype("int8").to_numpy()
            pos_weight = min(
                modeling_spec.boosting.positive_class_weight_cap,
                (len(y_sample) - int(y_sample.sum())) / max(1, int(y_sample.sum())),
            )
            bundle = fit_boosting_bundle(
                sample,
                categorical_features=contract.categorical_features,
                numeric_features=contract.numeric_features,
                target=modeling_spec.target,
                missing_category=modeling_spec.preprocessing.missing_category,
                max_categories=modeling_spec.boosting.max_categories,
                max_iter=robustness_spec.backtesting.max_iter,
                learning_rate=modeling_spec.boosting.learning_rate,
                max_leaf_nodes=modeling_spec.boosting.max_leaf_nodes,
                min_samples_leaf=modeling_spec.boosting.min_samples_leaf,
                l2_regularization=modeling_spec.boosting.l2_regularization,
                positive_class_weight=pos_weight,
                random_seed=robustness_spec.core.random_seed + fold_index,
            )

            y_parts: list[np.ndarray] = []
            p_parts: list[np.ndarray] = []
            columns = [modeling_spec.target, *contract.all_features]
            for frame in iter_time_batches(
                matrix,
                columns=columns,
                t0_column=modeling_spec.t0_column,
                start=eval_start,
                end=eval_end,
                batch_size=robustness_spec.core.batch_size,
            ):
                y_parts.append(frame[modeling_spec.target].astype("int8").to_numpy())
                p_parts.append(bundle.predict_proba(frame))
            y_eval = np.concatenate(y_parts)
            p_eval = np.concatenate(p_parts)
            split_name = f"backtest_{year}"
            metric_parts.append(
                metric_frame(
                    "hist_gradient_boosting_fixed_recipe",
                    split_name,
                    y_eval,
                    p_eval,
                    bins=modeling_spec.ranking.calibration_bins,
                )
            )
            ranking_parts.append(
                ranking_metrics(
                    "hist_gradient_boosting_fixed_recipe",
                    split_name,
                    y_eval,
                    p_eval,
                    robustness_spec.ranking.review_fractions,
                )
            )
            fold_rows.append(
                {
                    "evaluation_year": year,
                    "train_end": str((eval_start - pd.Timedelta(days=1)).date()),
                    "train_population_rows": train_stats["rows"],
                    "train_population_positives": train_stats["positives"],
                    "train_sample_rows": len(sample),
                    "train_sample_positives": int(y_sample.sum()),
                    "evaluation_rows": len(y_eval),
                    "evaluation_positives": int(y_eval.sum()),
                    "positive_class_weight": float(pos_weight),
                    "iterations_fitted": int(getattr(bundle.classifier, "n_iter_", robustness_spec.backtesting.max_iter)),
                    "used_consumed_test_2025": False,
                }
            )
    finally:
        con.close()

    metrics = pd.concat(metric_parts, ignore_index=True)
    ranking = pd.concat(ranking_parts, ignore_index=True)
    folds = pd.DataFrame.from_records(fold_rows)
    write_report(metrics, reports_root / "robustness" / "40_backtest_metrics.parquet")
    write_report(ranking, reports_root / "robustness" / "40_backtest_ranking.parquet")
    write_report(folds, reports_root / "robustness" / "40_backtest_folds.parquet")

    op = ranking.loc[np.isclose(ranking["review_fraction"], robustness_spec.backtesting.operational_fraction)]
    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="backtest_fold_count",
        category="temporal",
        passed=len(folds) >= robustness_spec.acceptance.min_backtest_folds,
        observed={"folds": len(folds), "years": folds["evaluation_year"].tolist()},
        requirement=f"at least {robustness_spec.acceptance.min_backtest_folds} chronological development folds are evaluated",
    )
    add_validation(
        records,
        check_id="backtest_never_uses_consumed_test",
        category="governance",
        passed=bool((folds["used_consumed_test_2025"] == False).all() and (folds["evaluation_year"] != robustness_spec.governance.consumed_test_year).all()),  # noqa: E712
        observed={"consumed_test_year": robustness_spec.governance.consumed_test_year, "evaluation_years": folds["evaluation_year"].tolist()},
        requirement="rolling-origin development backtests never use the consumed 2025 TEST period",
    )
    add_validation(
        records,
        check_id="backtest_population_sufficient",
        category="quality",
        passed=bool((folds["evaluation_rows"] >= robustness_spec.backtesting.min_evaluation_rows).all() and (folds["evaluation_positives"] >= robustness_spec.backtesting.min_evaluation_positives).all()),
        observed={"min_rows": int(folds["evaluation_rows"].min()), "min_positives": int(folds["evaluation_positives"].min())},
        requirement="every backtest fold has sufficient rows and positive outcomes",
    )
    add_validation(
        records,
        check_id="backtest_operational_lift",
        category="usefulness",
        passed=bool((op["lift_at_k"] > robustness_spec.acceptance.min_backtest_lift_at_operational_k).all()),
        observed={"operational_fraction": robustness_spec.backtesting.operational_fraction, "lifts": op[["split", "lift_at_k"]].to_dict(orient="records")},
        requirement="every development fold produces lift above random review at the frozen operational capacity",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "robustness" / "40_validation.parquet")

    manifest_path = write_manifest(
        manifest_dir / "m5_temporal_backtesting.json",
        {
            "milestone": "M5",
            "component": "40_temporal_backtesting",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": robustness_spec.schema_version,
            "benchmark_model_schema": modeling_spec.schema_version,
            "evaluation_years": list(robustness_spec.backtesting.evaluation_years),
            "consumed_test_year": robustness_spec.governance.consumed_test_year,
            "test_2025_used_for_selection": False,
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return BacktestingResult(metrics, ranking, folds, validation, manifest_path)
