from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import spearmanr

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.advanced import AdvancedSpec
from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec


OUTCOME_IMPLEMENTATION = "m8-75-survival-outcomes-v1"
MODEL_IMPLEMENTATION = "m8-76-cox-ph-v1"


@dataclass(frozen=True, slots=True)
class SurvivalOutcomesResult:
    artifact: Path
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_analysis(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


@dataclass(slots=True)
class SurvivalEncoder:
    categorical_features: tuple[str, ...]
    numeric_features: tuple[str, ...]
    missing_category: str
    category_frequencies: dict[str, dict[str, float]]
    numeric_medians: np.ndarray
    centers: np.ndarray
    scales: np.ndarray

    @property
    def feature_names(self) -> tuple[str, ...]:
        categorical = tuple(f"freq__{name}" for name in self.categorical_features)
        return (*categorical, *self.numeric_features)

    @classmethod
    def fit(
        cls,
        frame: pd.DataFrame,
        *,
        categorical_features: Sequence[str],
        numeric_features: Sequence[str],
        missing_category: str,
    ) -> "SurvivalEncoder":
        categorical = tuple(categorical_features)
        numeric = tuple(numeric_features)
        frequencies: dict[str, dict[str, float]] = {}
        cat_parts: list[np.ndarray] = []
        for column in categorical:
            values = frame[column].astype("string").fillna(missing_category).astype(str)
            mapping = values.value_counts(normalize=True, dropna=False).to_dict()
            frequencies[column] = {str(key): float(value) for key, value in mapping.items()}
            cat_parts.append(values.map(frequencies[column]).fillna(0.0).to_numpy(float)[:, None])

        if numeric:
            numeric_values = (
                frame.loc[:, numeric]
                .apply(pd.to_numeric, errors="coerce")
                .to_numpy(dtype=np.float64)
            )
            medians = np.nanmedian(numeric_values, axis=0)
            medians = np.where(np.isfinite(medians), medians, 0.0)
            missing = ~np.isfinite(numeric_values)
            if missing.any():
                numeric_values[missing] = np.take(medians, np.where(missing)[1])
        else:
            numeric_values = np.empty((len(frame), 0), dtype=np.float64)
            medians = np.empty(0, dtype=np.float64)

        raw = np.concatenate([*cat_parts, numeric_values], axis=1)
        if raw.shape[1] == 0:
            raise ValueError("Survival analysis requires at least one feature")
        centers = np.mean(raw, axis=0)
        scales = np.std(raw, axis=0)
        scales = np.where(np.isfinite(scales) & (scales > 1e-8), scales, 1.0)
        return cls(
            categorical_features=categorical,
            numeric_features=numeric,
            missing_category=missing_category,
            category_frequencies=frequencies,
            numeric_medians=medians.astype(np.float64),
            centers=centers.astype(np.float64),
            scales=scales.astype(np.float64),
        )

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        cat_parts: list[np.ndarray] = []
        for column in self.categorical_features:
            values = frame[column].astype("string").fillna(self.missing_category).astype(str)
            mapping = self.category_frequencies[column]
            cat_parts.append(values.map(mapping).fillna(0.0).to_numpy(float)[:, None])

        if self.numeric_features:
            numeric_values = (
                frame.loc[:, self.numeric_features]
                .apply(pd.to_numeric, errors="coerce")
                .to_numpy(dtype=np.float64)
            )
            missing = ~np.isfinite(numeric_values)
            if missing.any():
                numeric_values[missing] = np.take(
                    self.numeric_medians,
                    np.where(missing)[1],
                )
        else:
            numeric_values = np.empty((len(frame), 0), dtype=np.float64)

        raw = np.concatenate([*cat_parts, numeric_values], axis=1)
        transformed = (raw - self.centers) / self.scales
        return np.asarray(transformed, dtype=np.float64)


@dataclass(slots=True)
class CoxPHBundle:
    encoder: SurvivalEncoder
    coefficients: np.ndarray
    baseline_times: np.ndarray
    baseline_cumulative_hazard: np.ndarray
    horizon_days: int
    l2_penalty: float
    optimizer_success: bool
    optimizer_message: str

    def predict_linear_risk(self, frame: pd.DataFrame) -> np.ndarray:
        matrix = self.encoder.transform(frame)
        return np.asarray(matrix @ self.coefficients, dtype=np.float64)

    def predict_survival(
        self,
        frame: pd.DataFrame,
        horizons: Sequence[int],
    ) -> np.ndarray:
        linear = np.clip(self.predict_linear_risk(frame), -30.0, 30.0)
        relative_risk = np.exp(linear)
        outputs: list[np.ndarray] = []
        for horizon in horizons:
            idx = int(np.searchsorted(self.baseline_times, horizon, side="right") - 1)
            cumulative = 0.0 if idx < 0 else float(self.baseline_cumulative_hazard[idx])
            outputs.append(np.exp(-cumulative * relative_risk))
        return np.column_stack(outputs)


@dataclass(frozen=True, slots=True)
class SurvivalAnalysisResult:
    model_artifact: Path
    metrics: pd.DataFrame
    km_curves: pd.DataFrame
    calibration: pd.DataFrame
    ph_diagnostics: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_gate(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def kaplan_meier_table(
    durations: Sequence[int] | np.ndarray,
    events: Sequence[int] | np.ndarray,
) -> pd.DataFrame:
    duration = np.asarray(durations, dtype=np.int64)
    observed = np.asarray(events, dtype=np.int8)
    if len(duration) != len(observed) or len(duration) == 0:
        raise ValueError("Kaplan-Meier requires equally sized non-empty arrays")
    if (duration < 0).any() or not np.isin(observed, [0, 1]).all():
        raise ValueError("Invalid survival duration/event arrays")

    survival = 1.0
    records: list[dict[str, Any]] = []
    for time in np.unique(duration):
        at_risk = int(np.sum(duration >= time))
        events_at_time = int(np.sum((duration == time) & (observed == 1)))
        censored_at_time = int(np.sum((duration == time) & (observed == 0)))
        if at_risk > 0 and events_at_time > 0:
            survival *= 1.0 - events_at_time / at_risk
        records.append(
            {
                "time_days": int(time),
                "at_risk": at_risk,
                "events": events_at_time,
                "censored": censored_at_time,
                "survival_probability": float(survival),
                "cumulative_incidence": float(1.0 - survival),
            }
        )
    return pd.DataFrame.from_records(records)


def _fenwick_add(tree: np.ndarray, index: int, value: int) -> None:
    cursor = index + 1
    while cursor < len(tree):
        tree[cursor] += value
        cursor += cursor & -cursor


def _fenwick_sum(tree: np.ndarray, index: int) -> int:
    if index < 0:
        return 0
    total = 0
    cursor = index + 1
    while cursor > 0:
        total += int(tree[cursor])
        cursor -= cursor & -cursor
    return total


def harrell_c_index(
    durations: Sequence[int] | np.ndarray,
    events: Sequence[int] | np.ndarray,
    risk_scores: Sequence[float] | np.ndarray,
) -> float:
    duration = np.asarray(durations, dtype=np.int64)
    observed = np.asarray(events, dtype=np.int8)
    scores = np.asarray(risk_scores, dtype=np.float64)
    if not (len(duration) == len(observed) == len(scores)) or len(duration) == 0:
        raise ValueError("C-index requires equally sized non-empty arrays")
    if not np.isfinite(scores).all():
        raise ValueError("C-index risk scores must be finite")

    unique_scores = np.unique(scores)
    ranks = np.searchsorted(unique_scores, scores)
    tree = np.zeros(len(unique_scores) + 1, dtype=np.int64)
    concordant = 0.0
    comparable = 0
    active = 0

    order = np.argsort(-duration, kind="stable")
    sorted_duration = duration[order]
    position = 0
    while position < len(order):
        end = position + 1
        while end < len(order) and sorted_duration[end] == sorted_duration[position]:
            end += 1
        group_indices = order[position:end]
        event_indices = group_indices[observed[group_indices] == 1]
        for idx in event_indices:
            rank = int(ranks[idx])
            less = _fenwick_sum(tree, rank - 1)
            less_or_equal = _fenwick_sum(tree, rank)
            equal = less_or_equal - less
            concordant += less + 0.5 * equal
            comparable += active
        for idx in group_indices:
            _fenwick_add(tree, int(ranks[idx]), 1)
            active += 1
        position = end

    return float(concordant / comparable) if comparable else float("nan")


def _cox_group_arrays(
    matrix: np.ndarray,
    durations: np.ndarray,
    events: np.ndarray,
    horizon_days: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bins = np.clip(durations.astype(np.int64), 0, horizon_days)
    event_counts = np.bincount(
        bins,
        weights=events.astype(np.float64),
        minlength=horizon_days + 1,
    )
    event_x = np.zeros((horizon_days + 1, matrix.shape[1]), dtype=np.float64)
    event_rows = events.astype(bool)
    np.add.at(event_x, bins[event_rows], matrix[event_rows])
    return bins, event_counts, event_x


def fit_cox_ph(
    matrix: np.ndarray,
    durations: np.ndarray,
    events: np.ndarray,
    *,
    horizon_days: int,
    l2_penalty: float,
    max_iter: int,
    tolerance: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, bool, str]:
    x = np.asarray(matrix, dtype=np.float64)
    duration = np.asarray(durations, dtype=np.int64)
    observed = np.asarray(events, dtype=np.int8)
    if x.ndim != 2 or len(x) != len(duration) or len(x) != len(observed):
        raise ValueError("Cox inputs have incompatible shapes")
    if int(observed.sum()) == 0:
        raise ValueError("Cox model cannot be fit without observed events")

    bins, event_counts, event_x = _cox_group_arrays(
        x,
        duration,
        observed,
        horizon_days,
    )
    event_times = np.flatnonzero(event_counts > 0)
    total_event_x = event_x.sum(axis=0)

    def objective(beta: np.ndarray) -> tuple[float, np.ndarray]:
        eta = np.clip(x @ beta, -30.0, 30.0)
        weights = np.exp(eta)
        risk_by_bin = np.bincount(
            bins,
            weights=weights,
            minlength=horizon_days + 1,
        )
        risk_sum = np.cumsum(risk_by_bin[::-1])[::-1]
        risk_x_by_bin = np.zeros((horizon_days + 1, x.shape[1]), dtype=np.float64)
        np.add.at(risk_x_by_bin, bins, weights[:, None] * x)
        risk_x_sum = np.cumsum(risk_x_by_bin[::-1], axis=0)[::-1]

        denominators = np.maximum(risk_sum[event_times], 1e-12)
        log_likelihood = float(total_event_x @ beta)
        log_likelihood -= float(
            np.sum(event_counts[event_times] * np.log(denominators))
        )
        weighted_means = risk_x_sum[event_times] / denominators[:, None]
        gradient_ll = total_event_x - np.sum(
            event_counts[event_times, None] * weighted_means,
            axis=0,
        )
        penalty = 0.5 * l2_penalty * float(beta @ beta)
        objective_value = -log_likelihood + penalty
        gradient = -gradient_ll + l2_penalty * beta
        return objective_value, gradient

    initial = np.zeros(x.shape[1], dtype=np.float64)
    result = minimize(
        fun=lambda beta: objective(beta),
        x0=initial,
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": max_iter, "ftol": tolerance, "gtol": tolerance},
    )
    beta = np.asarray(result.x, dtype=np.float64)

    eta = np.clip(x @ beta, -30.0, 30.0)
    weights = np.exp(eta)
    risk_by_bin = np.bincount(
        bins,
        weights=weights,
        minlength=horizon_days + 1,
    )
    risk_sum = np.cumsum(risk_by_bin[::-1])[::-1]
    increments = np.zeros(horizon_days + 1, dtype=np.float64)
    valid = (event_counts > 0) & (risk_sum > 0)
    increments[valid] = event_counts[valid] / risk_sum[valid]
    cumulative = np.cumsum(increments)
    times = np.flatnonzero(valid).astype(np.int64)
    baseline = cumulative[times].astype(np.float64)
    return beta, times, baseline, bool(result.success), str(result.message)


def _calibration_table(
    predicted_event: np.ndarray,
    observed_event: np.ndarray,
    *,
    horizon: int,
    bins: int,
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "predicted_event_probability": predicted_event,
            "observed_event": observed_event.astype(np.int8),
        }
    )
    unique = int(frame["predicted_event_probability"].nunique())
    q = max(1, min(bins, unique))
    if q == 1:
        frame["calibration_bin"] = 0
    else:
        frame["calibration_bin"] = pd.qcut(
            frame["predicted_event_probability"],
            q=q,
            labels=False,
            duplicates="drop",
        )
    grouped = (
        frame.groupby("calibration_bin", observed=True)
        .agg(
            rows=("observed_event", "size"),
            predicted_mean=("predicted_event_probability", "mean"),
            observed_rate=("observed_event", "mean"),
        )
        .reset_index()
    )
    grouped.insert(0, "horizon_days", horizon)
    return grouped


def _ph_diagnostics(
    matrix: np.ndarray,
    durations: np.ndarray,
    events: np.ndarray,
    coefficients: np.ndarray,
    feature_names: Sequence[str],
    *,
    top_k: int,
) -> pd.DataFrame:
    event_mask = events.astype(bool)
    if int(event_mask.sum()) < 3:
        return pd.DataFrame(
            columns=["feature", "coefficient", "schoenfeld_time_spearman", "abs_correlation"]
        )

    eta = np.clip(matrix @ coefficients, -30.0, 30.0)
    weights = np.exp(eta)
    order = np.argsort(durations, kind="stable")
    sorted_duration = durations[order]
    sorted_matrix = matrix[order]
    sorted_weights = weights[order]
    suffix_weight = np.cumsum(sorted_weights[::-1])[::-1]
    suffix_weighted_x = np.cumsum(
        (sorted_weights[:, None] * sorted_matrix)[::-1],
        axis=0,
    )[::-1]

    event_positions = np.flatnonzero(events[order] == 1)
    event_times = sorted_duration[event_positions]
    residuals = np.empty((len(event_positions), matrix.shape[1]), dtype=np.float64)
    for out_idx, position in enumerate(event_positions):
        time = sorted_duration[position]
        risk_start = int(np.searchsorted(sorted_duration, time, side="left"))
        denominator = max(float(suffix_weight[risk_start]), 1e-12)
        expected = suffix_weighted_x[risk_start] / denominator
        residuals[out_idx] = sorted_matrix[position] - expected

    rows: list[dict[str, Any]] = []
    for index, name in enumerate(feature_names):
        corr = spearmanr(event_times, residuals[:, index], nan_policy="omit").statistic
        value = float(corr) if np.isfinite(corr) else 0.0
        rows.append(
            {
                "feature": str(name),
                "coefficient": float(coefficients[index]),
                "schoenfeld_time_spearman": value,
                "abs_correlation": abs(value),
            }
        )
    frame = pd.DataFrame.from_records(rows)
    return frame.sort_values("abs_correlation", ascending=False).head(top_k).reset_index(drop=True)


def build_survival_outcomes(
    *,
    root: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    advanced_spec: AdvancedSpec,
) -> SurvivalOutcomesResult:
    from argos.common.duckdb import connect
    from argos.gold.utils import copy_query, parquet_source

    matrix_path = root / advanced_spec.artifacts.development_matrix
    labels_path = root / "data" / "gold" / "labels" / f"{gold_spec.target.name}.parquet"
    if not matrix_path.exists() or not labels_path.exists():
        raise FileNotFoundError("M8 survival outcomes require M8 matrix and M3 labels")

    artifact = root / advanced_spec.artifacts.survival_outcomes
    con = connect(
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        matrix = parquet_source(matrix_path)
        labels = parquet_source(labels_path)
        horizon = advanced_spec.survival.horizon_days
        copy_query(
            con,
            f"""
            SELECT
                m.contract_id,
                m.t0,
                m.split,
                CASE WHEN l.{modeling_spec.target} = 1 THEN 1 ELSE 0 END::TINYINT
                    AS event_observed,
                CASE
                    WHEN l.{modeling_spec.target} = 1
                        THEN LEAST({horizon}, GREATEST(0, l.days_to_first_qualifying_event))
                    ELSE {horizon}
                END::INTEGER AS duration_days,
                {horizon}::INTEGER AS administrative_horizon_days,
                '{advanced_spec.schema_version}' AS _m8_schema_version
            FROM {matrix} m
            JOIN {labels} l USING (contract_id, t0)
            WHERE m.split IN ('train', 'validation')
            """,
            artifact,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=True,
        )
        source = parquet_source(artifact)
        stats = con.execute(
            f"""
            SELECT
                COUNT(*) AS rows,
                COUNT(DISTINCT contract_id) AS distinct_contracts,
                SUM(event_observed) AS events,
                COUNT(*) FILTER (WHERE event_observed=0) AS administratively_censored,
                COUNT(*) FILTER (WHERE duration_days IS NULL) AS null_duration,
                COUNT(*) FILTER (WHERE duration_days < 0 OR duration_days > {horizon})
                    AS invalid_duration,
                COUNT(*) FILTER (
                    WHERE event_observed=0 AND duration_days <> {horizon}
                ) AS invalid_admin_censoring
            FROM {source}
            """
        ).fetchdf().iloc[0]
        splits = con.execute(
            f"SELECT split, COUNT(*) AS rows, SUM(event_observed) AS events "
            f"FROM {source} GROUP BY 1 ORDER BY 1"
        ).fetchdf()
        matrix_rows = int(con.execute(f"SELECT COUNT(*) FROM {matrix}").fetchone()[0])
    finally:
        con.close()

    split_names = sorted(splits["split"].astype(str).tolist())
    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="survival_outcomes_grain",
        category="grain",
        passed=(
            int(stats["rows"]) == matrix_rows
            and int(stats["distinct_contracts"]) == matrix_rows
        ),
        observed={
            "rows": int(stats["rows"]),
            "distinct_contracts": int(stats["distinct_contracts"]),
            "m8_matrix_rows": matrix_rows,
        },
        requirement="one survival outcome row per M8 development contract",
    )
    add_validation(
        records,
        check_id="survival_outcomes_duration_valid",
        category="survival_semantics",
        passed=(
            int(stats["null_duration"]) == 0
            and int(stats["invalid_duration"]) == 0
        ),
        observed={
            "null_duration_rows": int(stats["null_duration"]),
            "invalid_duration_rows": int(stats["invalid_duration"]),
        },
        requirement=f"survival durations remain inside [0,{advanced_spec.survival.horizon_days}]",
    )
    add_validation(
        records,
        check_id="survival_administrative_censoring_valid",
        category="censoring",
        passed=int(stats["invalid_admin_censoring"]) == 0,
        observed={
            "administratively_censored": int(stats["administratively_censored"]),
            "invalid": int(stats["invalid_admin_censoring"]),
        },
        requirement="contracts without a 180-day event are censored administratively at day 180",
    )
    add_validation(
        records,
        check_id="survival_outcomes_development_only",
        category="evaluation_governance",
        passed=set(split_names).issubset(set(advanced_spec.governance.development_splits)),
        observed={"splits": split_names},
        requirement="survival development consumes TRAIN/VALIDATION only",
    )
    add_validation(
        records,
        check_id="survival_outcomes_events_present",
        category="survival_semantics",
        passed=int(stats["events"]) >= advanced_spec.survival.min_total_events,
        observed={"events": int(stats["events"])},
        requirement=(
            f"survival development has at least {advanced_spec.survival.min_total_events} "
            "observed target events"
        ),
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "advanced" / "75_validation.parquet")
    write_report(splits, reports_root / "advanced" / "75_survival_split_summary.parquet")

    manifest_path = root / advanced_spec.artifacts.survival_outcomes_manifest
    write_manifest(
        manifest_path,
        {
            "schema_version": advanced_spec.schema_version,
            "implementation": OUTCOME_IMPLEMENTATION,
            "artifact": str(artifact.relative_to(root)),
            "rows": int(stats["rows"]),
            "events": int(stats["events"]),
            "administratively_censored": int(stats["administratively_censored"]),
            "horizon_days": advanced_spec.survival.horizon_days,
            "event_semantics": gold_spec.target.included_event_types,
            "consumed_splits": split_names,
            "consumed_test_or_oot_for_selection": False,
        },
    )
    return SurvivalOutcomesResult(
        artifact=artifact,
        validation=validation,
        manifest_path=manifest_path,
    )


def build_survival_analysis(
    *,
    root: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    advanced_spec: AdvancedSpec,
) -> SurvivalAnalysisResult:
    from argos.common.duckdb import connect
    from argos.gold.utils import columns_of, parquet_source

    matrix_path = root / advanced_spec.artifacts.development_matrix
    outcomes_path = root / advanced_spec.artifacts.survival_outcomes
    if not matrix_path.exists() or not outcomes_path.exists():
        raise FileNotFoundError("M8 survival analysis requires matrix and survival outcomes")

    con = connect(
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        matrix = parquet_source(matrix_path)
        outcomes = parquet_source(outcomes_path)
        matrix_columns = columns_of(con, matrix)
        categorical = tuple(
            column
            for column in gold_spec.contract_features.categorical_candidates
            if column in matrix_columns
        )
        excluded = {
            modeling_spec.id_column,
            modeling_spec.t0_column,
            modeling_spec.split_column,
            modeling_spec.target,
            *categorical,
        }
        numeric = tuple(
            column
            for column in matrix_columns
            if column not in excluded and not column.startswith("_")
        )
        features = [*categorical, *numeric]
        quoted = ", ".join(f'm."{column}"' for column in features)
        base_select = (
            "m.contract_id, m.t0, m.split, o.duration_days, o.event_observed"
            + (f", {quoted}" if quoted else "")
        )
        train = con.execute(
            f"""
            SELECT {base_select}
            FROM {matrix} m
            JOIN {outcomes} o USING (contract_id, t0, split)
            WHERE m.split='train'
            ORDER BY hash(
                CAST(m.contract_id AS VARCHAR)
                || '::survival::{advanced_spec.survival.random_seed}'
            )
            LIMIT {advanced_spec.survival.max_train_rows}
            """
        ).fetchdf()
        validation = con.execute(
            f"""
            SELECT {base_select}
            FROM {matrix} m
            JOIN {outcomes} o USING (contract_id, t0, split)
            WHERE m.split='validation'
            ORDER BY hash(
                CAST(m.contract_id AS VARCHAR)
                || '::survival-validation::{advanced_spec.survival.random_seed}'
            )
            LIMIT {advanced_spec.survival.max_validation_rows}
            """
        ).fetchdf()
        split_totals = con.execute(
            f"""
            SELECT split, COUNT(*) AS rows, SUM(event_observed) AS events
            FROM {outcomes}
            GROUP BY 1 ORDER BY 1
            """
        ).fetchdf()
    finally:
        con.close()

    train_events = int(train["event_observed"].sum())
    validation_events = int(validation["event_observed"].sum())
    encoder = SurvivalEncoder.fit(
        train,
        categorical_features=categorical,
        numeric_features=numeric,
        missing_category=modeling_spec.preprocessing.missing_category,
    )
    x_train = encoder.transform(train)
    x_validation = encoder.transform(validation)
    train_duration = train["duration_days"].to_numpy(dtype=np.int64)
    train_observed = train["event_observed"].to_numpy(dtype=np.int8)
    valid_duration = validation["duration_days"].to_numpy(dtype=np.int64)
    valid_observed = validation["event_observed"].to_numpy(dtype=np.int8)

    coefficients, baseline_times, baseline_hazard, success, message = fit_cox_ph(
        x_train,
        train_duration,
        train_observed,
        horizon_days=advanced_spec.survival.horizon_days,
        l2_penalty=advanced_spec.survival.l2_penalty,
        max_iter=advanced_spec.survival.max_iter,
        tolerance=advanced_spec.survival.tolerance,
    )
    bundle = CoxPHBundle(
        encoder=encoder,
        coefficients=coefficients,
        baseline_times=baseline_times,
        baseline_cumulative_hazard=baseline_hazard,
        horizon_days=advanced_spec.survival.horizon_days,
        l2_penalty=advanced_spec.survival.l2_penalty,
        optimizer_success=success,
        optimizer_message=message,
    )
    model_artifact = root / advanced_spec.artifacts.survival_model
    model_artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_artifact, compress=3)

    train_risk = bundle.predict_linear_risk(train)
    valid_risk = bundle.predict_linear_risk(validation)
    train_c = harrell_c_index(train_duration, train_observed, train_risk)
    valid_c = harrell_c_index(valid_duration, valid_observed, valid_risk)

    horizons = tuple(advanced_spec.survival.evaluation_horizons)
    validation_survival = bundle.predict_survival(validation, horizons)
    train_km = kaplan_meier_table(train_duration, train_observed)
    validation_km = kaplan_meier_table(valid_duration, valid_observed)
    train_km.insert(0, "split", "train")
    validation_km.insert(0, "split", "validation")
    km_curves = pd.concat([train_km, validation_km], ignore_index=True)

    metric_rows: list[dict[str, Any]] = [
        {
            "split": "train",
            "metric": "harrell_c_index",
            "horizon_days": None,
            "value": train_c,
        },
        {
            "split": "validation",
            "metric": "harrell_c_index",
            "horizon_days": None,
            "value": valid_c,
        },
    ]
    calibration_parts: list[pd.DataFrame] = []
    briers: list[float] = []
    for column_index, horizon in enumerate(horizons):
        predicted_event = 1.0 - validation_survival[:, column_index]
        observed_event = ((valid_observed == 1) & (valid_duration <= horizon)).astype(np.int8)
        brier = float(np.mean(np.square(predicted_event - observed_event)))
        briers.append(brier)
        km_at_horizon = validation_km.loc[
            validation_km["time_days"] <= horizon,
            "cumulative_incidence",
        ]
        observed_rate = float(observed_event.mean())
        km_incidence = float(km_at_horizon.iloc[-1]) if not km_at_horizon.empty else 0.0
        metric_rows.extend(
            [
                {
                    "split": "validation",
                    "metric": "brier_event_probability",
                    "horizon_days": int(horizon),
                    "value": brier,
                },
                {
                    "split": "validation",
                    "metric": "observed_event_rate",
                    "horizon_days": int(horizon),
                    "value": observed_rate,
                },
                {
                    "split": "validation",
                    "metric": "kaplan_meier_cumulative_incidence",
                    "horizon_days": int(horizon),
                    "value": km_incidence,
                },
            ]
        )
        calibration_parts.append(
            _calibration_table(
                predicted_event,
                observed_event,
                horizon=int(horizon),
                bins=advanced_spec.survival.calibration_bins,
            )
        )
    metric_rows.append(
        {
            "split": "validation",
            "metric": "mean_brier_over_configured_horizons",
            "horizon_days": None,
            "value": float(np.mean(briers)),
        }
    )
    metrics = pd.DataFrame.from_records(metric_rows)
    calibration = pd.concat(calibration_parts, ignore_index=True)
    ph_diagnostics = _ph_diagnostics(
        x_train,
        train_duration,
        train_observed,
        coefficients,
        encoder.feature_names,
        top_k=advanced_spec.survival.ph_diagnostic_top_k,
    )

    write_report(metrics, reports_root / "advanced" / "76_survival_metrics.parquet")
    write_report(km_curves, reports_root / "advanced" / "76_kaplan_meier.parquet")
    write_report(calibration, reports_root / "advanced" / "76_survival_calibration.parquet")
    write_report(
        ph_diagnostics,
        reports_root / "advanced" / "76_ph_diagnostics.parquet",
    )

    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="survival_train_events_sufficient",
        category="survival_population",
        passed=train_events >= advanced_spec.survival.min_train_events,
        observed={"sample_rows": len(train), "events": train_events},
        requirement=(
            f"survival TRAIN sample has >= {advanced_spec.survival.min_train_events} events"
        ),
    )
    add_validation(
        records,
        check_id="survival_validation_events_sufficient",
        category="survival_population",
        passed=validation_events >= advanced_spec.survival.min_validation_events,
        observed={"sample_rows": len(validation), "events": validation_events},
        requirement=(
            "survival VALIDATION sample has >= "
            f"{advanced_spec.survival.min_validation_events} events"
        ),
    )
    add_validation(
        records,
        check_id="survival_cox_optimizer",
        category="model",
        passed=success and np.isfinite(coefficients).all(),
        observed={"success": success, "message": message, "features": len(coefficients)},
        requirement="penalized Cox PH optimization converges to finite coefficients",
    )
    add_validation(
        records,
        check_id="survival_metrics_finite",
        category="quality",
        passed=bool(np.isfinite(metrics["value"].to_numpy(dtype=float)).all()),
        observed={"metric_rows": len(metrics), "validation_c_index": valid_c},
        requirement="survival discrimination/calibration metrics are finite",
    )
    add_validation(
        records,
        check_id="survival_probability_contract",
        category="quality",
        passed=bool(
            np.isfinite(validation_survival).all()
            and ((validation_survival >= 0.0) & (validation_survival <= 1.0)).all()
            and np.all(np.diff(validation_survival, axis=1) <= 1e-10)
        ),
        observed={"horizons": list(horizons)},
        requirement="predicted survival probabilities are finite, bounded and non-increasing",
    )
    add_validation(
        records,
        check_id="survival_train_validation_only",
        category="evaluation_governance",
        passed=set(split_totals["split"].astype(str)).issubset(
            set(advanced_spec.governance.development_splits)
        ),
        observed={
            "consumed_splits": split_totals["split"].astype(str).tolist(),
            "test_consumed": False,
            "oot_consumed": False,
        },
        requirement="M8 survival fitting/evaluation never consumes TEST 2025 or OOT 2026",
    )
    add_validation(
        records,
        check_id="survival_horizons_contract",
        category="survival_semantics",
        passed=(
            tuple(sorted(horizons)) == horizons
            and horizons[-1] == advanced_spec.survival.horizon_days
        ),
        observed={"evaluation_horizons": list(horizons)},
        requirement="configured survival horizons are ordered and end at the target horizon",
    )
    validation_report = pd.DataFrame.from_records(records)
    write_report(validation_report, reports_root / "advanced" / "76_validation.parquet")

    manifest_path = root / advanced_spec.artifacts.survival_manifest
    write_manifest(
        manifest_path,
        {
            "schema_version": advanced_spec.schema_version,
            "implementation": MODEL_IMPLEMENTATION,
            "model_artifact": str(model_artifact.relative_to(root)),
            "fitted_split": "train",
            "evaluated_split": "validation",
            "train_sample_rows": len(train),
            "train_events": train_events,
            "validation_sample_rows": len(validation),
            "validation_events": validation_events,
            "feature_count": len(encoder.feature_names),
            "evaluation_horizons": list(horizons),
            "administrative_horizon_days": advanced_spec.survival.horizon_days,
            "validation_c_index": valid_c,
            "mean_validation_brier": float(np.mean(briers)),
            "optimizer_success": success,
            "optimizer_message": message,
            "consumed_test_or_oot_for_selection": False,
        },
    )
    return SurvivalAnalysisResult(
        model_artifact=model_artifact,
        metrics=metrics,
        km_curves=km_curves,
        calibration=calibration,
        ph_diagnostics=ph_diagnostics,
        validation=validation_report,
        manifest_path=manifest_path,
    )
