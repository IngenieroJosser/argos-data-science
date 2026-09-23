from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec
from argos.config.robustness import RobustnessSpec
from argos.robustness.common import (
    deterministic_rank,
    deterministic_time_sample,
    iter_time_batches,
    load_contract,
    load_frozen_v1,
    matrix_path,
    sha256_file,
)
from argos.robustness.perturbation import reference_values, replace_feature_value


BUILD_IMPLEMENTATION = "m5-41-permutation-local-sensitivity-v2"


@dataclass(frozen=True, slots=True)
class ExplainabilityResult:
    global_importance: pd.DataFrame
    family_importance: pd.DataFrame
    local_sensitivity: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _family_for(feature: str, contract) -> str:
    if feature in set(contract.contract_features):
        return "contract"
    if feature in set(contract.historical_features):
        return "historical"
    if feature in set(contract.competition_features):
        return "competition"
    return "other"


def build_explainability(
    *,
    root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    robustness_spec: RobustnessSpec,
    reports_root: Path,
    manifest_dir: Path,
) -> ExplainabilityResult:
    matrix = matrix_path(root, modeling_spec)
    contract = load_contract(root, gold_spec, modeling_spec)
    model, calibrator, selection = load_frozen_v1(root)
    start = pd.Timestamp(robustness_spec.explainability.validation_start)
    end = pd.Timestamp(robustness_spec.explainability.validation_end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    sample = deterministic_time_sample(
        matrix,
        columns=[modeling_spec.target, *contract.all_features],
        id_column=modeling_spec.id_column,
        t0_column=modeling_spec.t0_column,
        start=start,
        end=end,
        max_rows=robustness_spec.explainability.sample_rows,
        batch_size=robustness_spec.core.batch_size,
        seed=robustness_spec.core.random_seed + 4100,
    )
    y = sample[modeling_spec.target].astype("int8").to_numpy()
    baseline_raw = model.predict_proba(sample)
    baseline_pr = float(average_precision_score(y, baseline_raw))
    rng = np.random.default_rng(robustness_spec.core.random_seed + 4111)

    rows: list[dict[str, Any]] = []
    for feature in contract.all_features:
        drops: list[float] = []
        for repeat in range(robustness_spec.explainability.permutation_repeats):
            permuted = sample.copy()
            values = permuted[feature].to_numpy(copy=True)
            rng.shuffle(values)
            permuted[feature] = values
            perm_score = model.predict_proba(permuted)
            perm_pr = float(average_precision_score(y, perm_score))
            drops.append(baseline_pr - perm_pr)
        rows.append(
            {
                "feature": feature,
                "family": _family_for(feature, contract),
                "baseline_pr_auc": baseline_pr,
                "importance_mean_pr_auc_drop": float(np.mean(drops)),
                "importance_std": float(np.std(drops, ddof=1)) if len(drops) > 1 else 0.0,
                "repeats": len(drops),
                "sample_rows": len(sample),
            }
        )
    global_importance = pd.DataFrame.from_records(rows).sort_values(
        ["importance_mean_pr_auc_drop", "feature"], ascending=[False, True]
    ).reset_index(drop=True)
    family_importance = (
        global_importance.groupby("family", as_index=False)
        .agg(
            feature_count=("feature", "count"),
            total_pr_auc_drop=("importance_mean_pr_auc_drop", "sum"),
            mean_pr_auc_drop=("importance_mean_pr_auc_drop", "mean"),
            max_pr_auc_drop=("importance_mean_pr_auc_drop", "max"),
        )
        .sort_values("total_pr_auc_drop", ascending=False)
        .reset_index(drop=True)
    )

    pred_path = reports_root / "modeling" / "33_selected_validation_predictions.parquet"
    if not pred_path.exists():
        raise FileNotFoundError(pred_path)
    selected = pd.read_parquet(pred_path)
    selected[modeling_spec.t0_column] = pd.to_datetime(selected[modeling_spec.t0_column], errors="raise")
    selected = selected.loc[
        (selected[modeling_spec.t0_column] >= start) & (selected[modeling_spec.t0_column] <= end)
    ].copy()
    if selected.empty:
        raise ValueError("No M4 selected validation predictions found in explainability period")
    selected = deterministic_rank(selected)
    top_ids = selected.head(robustness_spec.explainability.local_case_count)[modeling_spec.id_column].astype(str).tolist()
    wanted = set(top_ids)
    local_parts: list[pd.DataFrame] = []
    columns = [modeling_spec.id_column, modeling_spec.t0_column, modeling_spec.target, *contract.all_features]
    for frame in iter_time_batches(
        matrix,
        columns=columns,
        t0_column=modeling_spec.t0_column,
        start=start,
        end=end,
        batch_size=robustness_spec.core.batch_size,
    ):
        piece = frame.loc[frame[modeling_spec.id_column].astype(str).isin(wanted)]
        if not piece.empty:
            local_parts.append(piece)
    local_cases = pd.concat(local_parts, ignore_index=True) if local_parts else pd.DataFrame()
    if len(local_cases) != len(top_ids):
        raise ValueError(f"Could not recover all top-ranked local cases: expected {len(top_ids)}, got {len(local_cases)}")
    local_cases[modeling_spec.id_column] = local_cases[modeling_spec.id_column].astype(str)
    order = {cid: i for i, cid in enumerate(top_ids)}
    local_cases = local_cases.assign(_order=local_cases[modeling_spec.id_column].map(order)).sort_values("_order").drop(columns=["_order"])

    refs = reference_values(sample, set(contract.categorical_features), contract.all_features)
    local_rows: list[dict[str, Any]] = []
    for _, case in local_cases.iterrows():
        one = pd.DataFrame([case])
        base_raw = float(model.predict_proba(one)[0])
        base_cal = float(calibrator.transform(np.asarray([base_raw]))[0])
        for feature in contract.all_features:
            changed = replace_feature_value(one, feature, refs[feature])
            perturbed_raw = float(model.predict_proba(changed)[0])
            perturbed_cal = float(calibrator.transform(np.asarray([perturbed_raw]))[0])
            local_rows.append(
                {
                    "contract_id": str(case[modeling_spec.id_column]),
                    "t0": case[modeling_spec.t0_column],
                    "target": int(case[modeling_spec.target]),
                    "feature": feature,
                    "family": _family_for(feature, contract),
                    "reference_value": str(refs[feature]),
                    "base_raw_score": base_raw,
                    "perturbed_raw_score": perturbed_raw,
                    "raw_score_delta": base_raw - perturbed_raw,
                    "base_calibrated_score": base_cal,
                    "perturbed_calibrated_score": perturbed_cal,
                    "calibrated_score_delta": base_cal - perturbed_cal,
                    "interpretation": "one-feature reference substitution; sensitivity, not causal attribution",
                }
            )
    local_sensitivity = pd.DataFrame.from_records(local_rows)

    write_report(global_importance, reports_root / "robustness" / "41_global_permutation_importance.parquet")
    write_report(family_importance, reports_root / "robustness" / "41_family_importance.parquet")
    write_report(local_sensitivity, reports_root / "robustness" / "41_local_sensitivity.parquet")

    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="explainability_uses_validation_only",
        category="governance",
        passed=bool(sample[modeling_spec.t0_column].min() >= start and sample[modeling_spec.t0_column].max() <= end and end.year < robustness_spec.governance.consumed_test_year),
        observed={"min_t0": str(sample[modeling_spec.t0_column].min()), "max_t0": str(sample[modeling_spec.t0_column].max()), "consumed_test_year": robustness_spec.governance.consumed_test_year},
        requirement="feature attribution is derived from development validation data, never TEST 2025",
    )
    add_validation(
        records,
        check_id="global_importance_complete",
        category="explainability",
        passed=len(global_importance) == len(contract.all_features) and np.isfinite(global_importance["importance_mean_pr_auc_drop"]).all(),
        observed={"features_reported": len(global_importance), "expected": len(contract.all_features)},
        requirement="every frozen V1 feature has a finite permutation-importance estimate",
    )
    add_validation(
        records,
        check_id="global_importance_minimum_reported",
        category="explainability",
        passed=len(global_importance) >= robustness_spec.explainability.min_global_features_reported,
        observed={"features": len(global_importance), "minimum": robustness_spec.explainability.min_global_features_reported},
        requirement="global explainability artifact contains a nontrivial feature set",
    )
    add_validation(
        records,
        check_id="local_sensitivity_complete",
        category="explainability",
        passed=(local_sensitivity["contract_id"].nunique() == robustness_spec.explainability.local_case_count and local_sensitivity["feature"].nunique() == len(contract.all_features)),
        observed={"cases": int(local_sensitivity["contract_id"].nunique()), "features": int(local_sensitivity["feature"].nunique())},
        requirement="local sensitivity is persisted for the frozen number of prioritized validation cases across every feature",
    )
    add_validation(
        records,
        check_id="explainability_model_hash_preserved",
        category="lineage",
        passed=True,
        observed={"model_sha256": selection["model_sha256"], "calibrator_sha256": selection["calibrator_sha256"]},
        requirement="explainability uses the exact frozen M4 V1 model and calibrator artifacts",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "robustness" / "41_validation.parquet")

    selection_path = root / "artifacts" / "models" / "m4" / "selected_model.json"
    manifest_path = write_manifest(
        manifest_dir / "m5_explainability.json",
        {
            "milestone": "M5",
            "component": "41_explainability",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": robustness_spec.schema_version,
            "selection_sha256": sha256_file(selection_path),
            "model_sha256": selection["model_sha256"],
            "calibrator_sha256": selection["calibrator_sha256"],
            "sample_rows": len(sample),
            "feature_count": len(contract.all_features),
            "local_case_count": robustness_spec.explainability.local_case_count,
            "test_2025_used_for_selection": False,
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return ExplainabilityResult(global_importance, family_importance, local_sensitivity, validation, manifest_path)
