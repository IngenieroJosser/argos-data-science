from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import quote_identifier, sql_string
from argos.common.validation import add_validation, write_manifest
from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec
from argos.config.robustness import RobustnessSpec
from argos.gold.utils import copy_query, parquet_source, require_columns
from argos.models.metrics import reliability_table
from argos.robustness.common import (
    deterministic_ranking_metrics,
    load_contract,
    load_frozen_v1,
    probability_metric_record,
    sha256_file,
)


BUILD_IMPLEMENTATION = "m5-45-fresh-oot-2026-v1"


@dataclass(frozen=True, slots=True)
class FreshOOTResult:
    artifact: Path
    predictions_path: Path
    metrics: pd.DataFrame
    ranking: pd.DataFrame
    reliability: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _paths(root: Path, reports_root: Path, manifest_dir: Path) -> dict[str, Path]:
    return {
        "artifact": root / "data" / "m5" / "fresh_oot_2026.parquet",
        "predictions": reports_root / "robustness" / "45_fresh_oot_predictions.parquet",
        "metrics": reports_root / "robustness" / "45_fresh_oot_metrics.parquet",
        "ranking": reports_root / "robustness" / "45_fresh_oot_ranking.parquet",
        "reliability": reports_root / "robustness" / "45_fresh_oot_reliability.parquet",
        "validation": reports_root / "robustness" / "45_validation.parquet",
        "manifest": manifest_dir / "m5_fresh_oot_2026.json",
    }


def _load_completed(paths: dict[str, Path], *, root: Path) -> FreshOOTResult | None:
    completed = [paths[k] for k in ["artifact", "predictions", "metrics", "ranking", "reliability", "validation", "manifest"]]
    if not all(p.exists() for p in completed):
        return None
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    _, _, selection = load_frozen_v1(root)
    if manifest.get("model_sha256") != selection.get("model_sha256"):
        raise ValueError("Completed fresh OOT artifact does not match current frozen V1 model hash")
    if manifest.get("calibrator_sha256") != selection.get("calibrator_sha256"):
        raise ValueError("Completed fresh OOT artifact does not match current frozen V1 calibrator hash")
    return FreshOOTResult(
        artifact=paths["artifact"],
        predictions_path=paths["predictions"],
        metrics=pd.read_parquet(paths["metrics"]),
        ranking=pd.read_parquet(paths["ranking"]),
        reliability=pd.read_parquet(paths["reliability"]),
        validation=pd.read_parquet(paths["validation"]),
        manifest_path=paths["manifest"],
    )


def build_fresh_oot_2026(
    *,
    root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    robustness_spec: RobustnessSpec,
    reports_root: Path,
    manifest_dir: Path,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> FreshOOTResult:
    paths = _paths(root, reports_root, manifest_dir)
    if robustness_spec.fresh_oot.reuse_completed_artifacts:
        completed = _load_completed(paths, root=root)
        if completed is not None:
            print("[45] completed fresh OOT evaluation detected; reusing frozen artifacts")
            return completed

    labels_path = root / "data" / "gold" / "labels" / f"{gold_spec.target.name}.parquet"
    contract_path = root / "data" / "gold" / "features" / "contract_features.parquet"
    historical_path = root / "data" / "gold" / "features" / "historical_features.parquet"
    competition_path = root / "data" / "gold" / "features" / "competition_features.parquet"
    for path in [labels_path, contract_path, historical_path, competition_path]:
        if not path.exists():
            raise FileNotFoundError(path)

    contract = load_contract(root, gold_spec, modeling_spec)
    labels = parquet_source(labels_path)
    contract_source = parquet_source(contract_path)
    historical_source = parquet_source(historical_path)
    competition_source = parquet_source(competition_path)
    con = connect(
        temp_directory=temp_directory,
        threads=robustness_spec.runtime.duckdb_threads,
        memory_limit=robustness_spec.runtime.duckdb_memory_limit,
    )
    try:
        require_columns(con, labels, ["contract_id", "t0", "eligible", gold_spec.target.name, "label_cutoff"], label="Gold labels")
        max_eligible_t0 = con.execute(
            f"""
            SELECT MAX(t0)
            FROM {labels}
            WHERE eligible
              AND EXTRACT(YEAR FROM t0) = {robustness_spec.governance.fresh_oot_year}
            """
        ).fetchone()[0]
        if max_eligible_t0 is None:
            raise ValueError("No fully observed eligible 2026 cohort exists for a fresh OOT holdout")
        oot_start = pd.Timestamp(robustness_spec.fresh_oot.start)
        oot_end = min(pd.Timestamp(max_eligible_t0), pd.Timestamp(robustness_spec.fresh_oot.max_end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1))
        if oot_end < oot_start:
            raise ValueError(f"Fresh OOT window is empty: {oot_start} > {oot_end}")

        contract_projection = [f"c.{quote_identifier(f)} AS {quote_identifier(f)}" for f in contract.contract_features]
        historical_projection = [f"h.{quote_identifier(f)} AS {quote_identifier(f)}" for f in contract.historical_features]
        competition_projection = [f"q.{quote_identifier(f)} AS {quote_identifier(f)}" for f in contract.competition_features]
        projection = [
            "l.contract_id",
            "l.t0",
            f"l.{quote_identifier(modeling_spec.target)} AS {quote_identifier(modeling_spec.target)}",
            *contract_projection,
            *historical_projection,
            *competition_projection,
            f"{sql_string(robustness_spec.schema_version)} AS _m5_schema_version",
        ]
        query = f"""
            SELECT {', '.join(projection)}
            FROM {labels} l
            JOIN {contract_source} c USING (contract_id)
            JOIN {historical_source} h USING (contract_id)
            JOIN {competition_source} q USING (contract_id)
            WHERE l.eligible
              AND l.{quote_identifier(modeling_spec.target)} IS NOT NULL
              AND l.t0 >= TIMESTAMP {sql_string(oot_start.strftime('%Y-%m-%d %H:%M:%S'))}
              AND l.t0 <= TIMESTAMP {sql_string(oot_end.strftime('%Y-%m-%d %H:%M:%S'))}
        """
        print(f"[45] materializing untouched eligible OOT cohort: {oot_start.date()} through {oot_end.date()}...")
        copy_query(
            con,
            query,
            paths["artifact"],
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=overwrite or paths["artifact"].exists(),
        )
        source = parquet_source(paths["artifact"])
        stats = con.execute(
            f"""
            SELECT COUNT(*) AS row_count,
                   COUNT(DISTINCT contract_id) AS distinct_contracts,
                   COUNT(*) FILTER (WHERE {quote_identifier(modeling_spec.target)}=1) AS positives,
                   MIN(t0) AS min_t0,
                   MAX(t0) AS max_t0
            FROM {source}
            """
        ).fetchdf().iloc[0]
    finally:
        con.close()

    model, calibrator, selection = load_frozen_v1(root)
    pf = pq.ParquetFile(paths["artifact"])
    pred_parts: list[pd.DataFrame] = []
    requested = [modeling_spec.id_column, modeling_spec.t0_column, modeling_spec.target, *contract.all_features]
    for batch in pf.iter_batches(batch_size=robustness_spec.core.batch_size, columns=requested):
        frame = batch.to_pandas()
        raw = model.predict_proba(frame)
        score = np.asarray(calibrator.transform(raw), dtype=np.float64)
        out = frame[[modeling_spec.id_column, modeling_spec.t0_column, modeling_spec.target]].copy()
        out["raw_score"] = raw
        out["score"] = score
        pred_parts.append(out)
    predictions = pd.concat(pred_parts, ignore_index=True)
    y = predictions[modeling_spec.target].astype("int8").to_numpy()
    p = predictions["score"].to_numpy(dtype=np.float64)
    metrics = pd.DataFrame.from_records([
        probability_metric_record(
            "ARGOS_V1_frozen",
            "fresh_oot_2026",
            y,
            p,
            modeling_spec.ranking.calibration_bins,
        )
    ])
    ranking = deterministic_ranking_metrics(
        predictions,
        target=modeling_spec.target,
        review_fractions=robustness_spec.ranking.review_fractions,
        model_name="ARGOS_V1_frozen",
        split="fresh_oot_2026",
    )
    reliability = reliability_table(y, p, bins=modeling_spec.ranking.calibration_bins)
    reliability.insert(0, "model", "ARGOS_V1_frozen")
    reliability.insert(1, "split", "fresh_oot_2026")

    write_report(predictions, paths["predictions"])
    write_report(metrics, paths["metrics"])
    write_report(ranking, paths["ranking"])
    write_report(reliability, paths["reliability"])

    op = ranking.loc[np.isclose(ranking["review_fraction"], robustness_spec.fresh_oot.operational_fraction)].iloc[0]
    metric = metrics.iloc[0]
    final_manifest_path = manifest_dir / "m4_final_test.json"
    selection_path = root / "artifacts" / "models" / "m4" / "selected_model.json"
    hash_errors: list[str] = []
    if final_manifest_path.exists():
        final_manifest = json.loads(final_manifest_path.read_text(encoding="utf-8"))
        if final_manifest.get("model_sha256") != selection.get("model_sha256"):
            hash_errors.append("model")
        if final_manifest.get("calibrator_sha256") != selection.get("calibrator_sha256"):
            hash_errors.append("calibrator")
        if final_manifest.get("selection_sha256") != sha256_file(selection_path):
            hash_errors.append("selection")
    else:
        hash_errors.append("m4_final_test_manifest_missing")

    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="fresh_oot_population_sufficient",
        category="holdout",
        passed=int(stats["row_count"]) >= robustness_spec.fresh_oot.min_rows and int(stats["positives"]) >= robustness_spec.fresh_oot.min_positives,
        observed={"rows": int(stats["row_count"]), "positives": int(stats["positives"]), "minimum_rows": robustness_spec.fresh_oot.min_rows, "minimum_positives": robustness_spec.fresh_oot.min_positives},
        requirement="fresh OOT cohort has enough fully observed contracts and positives for an informative evaluation",
    )
    add_validation(
        records,
        check_id="fresh_oot_strictly_after_consumed_test",
        category="governance",
        passed=pd.Timestamp(stats["min_t0"]).year > robustness_spec.governance.consumed_test_year,
        observed={"min_t0": str(stats["min_t0"]), "max_t0": str(stats["max_t0"]), "consumed_test_year": robustness_spec.governance.consumed_test_year},
        requirement="fresh OOT cohort starts strictly after consumed TEST 2025",
    )
    add_validation(
        records,
        check_id="fresh_oot_grain_unique",
        category="grain",
        passed=int(stats["row_count"]) == int(stats["distinct_contracts"]) == len(predictions),
        observed={"rows": int(stats["row_count"]), "distinct_contracts": int(stats["distinct_contracts"]), "predictions": len(predictions)},
        requirement="fresh OOT evaluation has one prediction per contract",
    )
    add_validation(
        records,
        check_id="fresh_oot_uses_exact_frozen_v1",
        category="lineage",
        passed=len(hash_errors) <= robustness_spec.acceptance.max_model_hash_mismatches,
        observed={"hash_errors": hash_errors, "model_sha256": selection["model_sha256"], "calibrator_sha256": selection["calibrator_sha256"]},
        requirement="fresh OOT scoring uses exactly the M4 model/calibrator frozen before any 2026 holdout access",
    )
    add_validation(
        records,
        check_id="fresh_oot_pr_auc_above_prevalence",
        category="usefulness",
        passed=float(metric["pr_auc"]) > float(metric["prevalence"]) * robustness_spec.acceptance.min_fresh_oot_pr_auc_over_prevalence,
        observed={"pr_auc": float(metric["pr_auc"]), "prevalence": float(metric["prevalence"]), "required_multiplier": robustness_spec.acceptance.min_fresh_oot_pr_auc_over_prevalence},
        requirement="frozen V1 has PR-AUC above the no-skill prevalence reference on the untouched 2026 cohort",
    )
    add_validation(
        records,
        check_id="fresh_oot_lift_operational_k",
        category="usefulness",
        passed=float(op["lift_at_k"]) > robustness_spec.acceptance.min_fresh_oot_lift_at_operational_k,
        observed={"fraction": robustness_spec.fresh_oot.operational_fraction, "lift_at_k": float(op["lift_at_k"]), "minimum": robustness_spec.acceptance.min_fresh_oot_lift_at_operational_k},
        requirement="frozen V1 remains useful above random review at the operational capacity on fresh OOT data",
    )
    add_validation(
        records,
        check_id="fresh_oot_probabilities_finite",
        category="quality",
        passed=bool(np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()),
        observed={"min": float(p.min()), "max": float(p.max())},
        requirement="fresh OOT calibrated scores are finite probabilities",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, paths["validation"])

    manifest_path = write_manifest(
        paths["manifest"],
        {
            "milestone": "M5",
            "component": "45_fresh_oot_2026",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": robustness_spec.schema_version,
            "cohort_start": str(pd.Timestamp(stats["min_t0"]).date()),
            "cohort_end": str(pd.Timestamp(stats["max_t0"]).date()),
            "cohort_note": "partial-year 2026 cohort limited by 180-day label observability; seasonal representativeness is limited",
            "rows": int(stats["row_count"]),
            "positives": int(stats["positives"]),
            "selection_sha256": sha256_file(selection_path),
            "model_sha256": selection["model_sha256"],
            "calibrator_sha256": selection["calibrator_sha256"],
            "fresh_oot_consumed": True,
            "model_reselected_after_fresh_oot": False,
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return FreshOOTResult(paths["artifact"], paths["predictions"], metrics, ranking, reliability, validation, manifest_path)
