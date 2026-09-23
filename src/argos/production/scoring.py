from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import sql_string
from argos.common.validation import add_validation, write_manifest
from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec
from argos.config.production import ProductionSpec
from argos.models.data import load_feature_contract
from argos.production.audit import append_audit_event
from argos.production.common import resolve, sha256_file, stable_batch_id
from argos.production.contracts import preflight_parquet
from argos.robustness.common import load_frozen_v1

BUILD_IMPLEMENTATION = "m6-52-idempotent-batch-scoring-v1"


@dataclass(frozen=True, slots=True)
class ScoringResult:
    batch_id: str
    scored_path: Path
    summary: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path
    reused_existing: bool

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())



def _existing_result(manifest_path: Path, scored_path: Path, reports_root: Path) -> ScoringResult | None:
    if not manifest_path.exists() or not scored_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("output_sha256") != sha256_file(scored_path):
        raise ValueError("Existing scored batch hash does not match its manifest")
    default_dir = reports_root / "production" / "batches" / str(manifest["batch_id"])
    validation_path = Path(str(manifest.get("validation_report", default_dir / "validation.parquet")))
    summary_path = Path(str(manifest.get("summary_report", default_dir / "summary.parquet")))
    if not validation_path.is_absolute():
        validation_path = reports_root.parents[0] / validation_path
    if not summary_path.is_absolute():
        summary_path = reports_root.parents[0] / summary_path
    if not validation_path.exists() or not summary_path.exists():
        return None
    return ScoringResult(str(manifest["batch_id"]), scored_path, pd.read_parquet(summary_path), pd.read_parquet(validation_path), manifest_path, True)


def score_batch(
    *,
    input_path: Path,
    root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    production_spec: ProductionSpec,
    reports_root: Path,
    manifest_dir: Path,
    temp_directory: Path | None = None,
) -> ScoringResult:
    profile, preflight_validation, contract_path = preflight_parquet(input_path, root=root, gold_spec=gold_spec, modeling_spec=modeling_spec, production_spec=production_spec, temp_directory=temp_directory)
    if not bool(preflight_validation.loc[preflight_validation["blocking"], "passed"].all()):
        raise ValueError("Scoring input failed blocking preflight checks")

    model, calibrator, selection = load_frozen_v1(root)
    input_hash = sha256_file(input_path)
    contract_hash = sha256_file(contract_path)
    batch_id = stable_batch_id(input_hash, str(selection["model_sha256"]), str(selection["calibrator_sha256"]), contract_hash)
    output_root = resolve(root, production_spec.scoring.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    scored_path = output_root / f"{batch_id}.parquet"
    manifest_path = manifest_dir / f"m6_scoring_{batch_id}.json"
    existing = _existing_result(manifest_path, scored_path, reports_root)
    if existing is not None:
        append_audit_event(root, log_path=production_spec.audit.log_path, event_type="scoring_batch_reused", actor="argos.system", payload={"batch_id": batch_id, "output_sha256": sha256_file(scored_path)})
        return existing

    contract = load_feature_contract(root, gold_spec, modeling_spec)
    requested = [production_spec.data_contract.id_column, production_spec.data_contract.t0_column, *contract.all_features]
    tmp_unsorted = output_root / f".{batch_id}.unsorted.parquet"
    if tmp_unsorted.exists():
        tmp_unsorted.unlink()
    writer: pq.ParquetWriter | None = None
    rows = 0
    score_min = math.inf
    score_max = -math.inf
    raw_min = math.inf
    raw_max = -math.inf
    try:
        parquet = pq.ParquetFile(input_path)
        for batch in parquet.iter_batches(batch_size=production_spec.core.batch_size, columns=requested):
            frame = batch.to_pandas()
            raw = np.asarray(model.predict_proba(frame), dtype=np.float64)
            score = np.asarray(calibrator.transform(raw), dtype=np.float64)
            out = frame[[production_spec.data_contract.id_column, production_spec.data_contract.t0_column]].copy()
            out["raw_score"] = raw
            out["score"] = score
            out["model_version"] = production_spec.core.model_version
            out["scoring_batch_id"] = batch_id
            table = pa.Table.from_pandas(out, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(tmp_unsorted, table.schema, compression="zstd")
            writer.write_table(table)
            rows += len(out)
            score_min = min(score_min, float(np.min(score)))
            score_max = max(score_max, float(np.max(score)))
            raw_min = min(raw_min, float(np.min(raw)))
            raw_max = max(raw_max, float(np.max(raw)))
    finally:
        if writer is not None:
            writer.close()
    if rows == 0:
        raise ValueError("Scoring produced zero rows")

    con = connect(temp_directory=temp_directory, threads=2, memory_limit="8GB")
    try:
        tmp_final = scored_path.with_suffix(".parquet.tmp")
        if tmp_final.exists():
            tmp_final.unlink()
        review_fraction = production_spec.scoring.operational_review_fraction
        query = f"""
            SELECT *,
                   ROW_NUMBER() OVER (ORDER BY score DESC, raw_score DESC, contract_id ASC) AS rank,
                   ROW_NUMBER() OVER (ORDER BY score DESC, raw_score DESC, contract_id ASC) <= CEIL(COUNT(*) OVER () * {review_fraction}) AS review_priority
            FROM read_parquet({sql_string(tmp_unsorted)})
            ORDER BY rank
        """
        con.execute(f"COPY ({query}) TO {sql_string(tmp_final)} (FORMAT PARQUET, COMPRESSION ZSTD)")
        tmp_final.replace(scored_path)
    finally:
        con.close()
        if tmp_unsorted.exists():
            tmp_unsorted.unlink()

    output_hash = sha256_file(scored_path)
    summary = pd.DataFrame.from_records([{
        "batch_id": batch_id,
        "rows": rows,
        "score_min": score_min,
        "score_max": score_max,
        "raw_score_min": raw_min,
        "raw_score_max": raw_max,
        "review_fraction": production_spec.scoring.operational_review_fraction,
        "review_rows": int(math.ceil(rows * production_spec.scoring.operational_review_fraction)),
        "input_sha256": input_hash,
        "output_sha256": output_hash,
    }])
    batch_report_dir = reports_root / "production" / "batches" / batch_id
    summary_path = write_report(summary, batch_report_dir / "summary.parquet")
    write_report(summary, reports_root / "production" / "52_scoring_summary.parquet")

    records: list[dict[str, Any]] = []
    add_validation(records, check_id="scoring_population_preserved", category="scoring", passed=rows == int(profile.loc[profile["metric"] == "row_count", "value"].iloc[0]), observed={"input_rows": int(profile.loc[profile["metric"] == "row_count", "value"].iloc[0]), "scored_rows": rows}, requirement="batch scoring emits exactly one score row for every preflight-approved observation")
    add_validation(records, check_id="scoring_probabilities_valid", category="scoring", passed=np.isfinite([score_min, score_max, raw_min, raw_max]).all() and 0.0 <= score_min <= score_max <= 1.0 and 0.0 <= raw_min <= raw_max <= 1.0, observed={"score_min": score_min, "score_max": score_max, "raw_min": raw_min, "raw_max": raw_max}, requirement="raw and calibrated outputs are finite probabilities")
    schema_names = set(pq.ParquetFile(scored_path).schema_arrow.names)
    forbidden = {modeling_spec.target, *production_spec.security.sensitive_columns}
    add_validation(records, check_id="scoring_output_minimizes_data", category="privacy", passed=not (schema_names & forbidden), observed={"forbidden_present": sorted(schema_names & forbidden)}, requirement="scoring output excludes target labels and explicitly forbidden sensitive columns")
    add_validation(records, check_id="ranking_contract_preserved", category="ranking", passed={"rank", "review_priority", "raw_score", "score", "contract_id"}.issubset(schema_names), observed={"tie_break": list(production_spec.scoring.tie_break)}, requirement="output persists deterministic rank and operational review flag")
    validation = pd.DataFrame.from_records(records)
    validation_path = write_report(validation, batch_report_dir / "validation.parquet")
    write_report(validation, reports_root / "production" / "52_validation.parquet")

    manifest_path = write_manifest(
        manifest_path,
        {
            "milestone": "M6",
            "component": "52_batch_scoring_and_idempotency",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": production_spec.schema_version,
            "batch_id": batch_id,
            "input": str(input_path),
            "input_sha256": input_hash,
            "contract_sha256": contract_hash,
            "model_sha256": selection["model_sha256"],
            "calibrator_sha256": selection["calibrator_sha256"],
            "output": str(scored_path),
            "output_sha256": output_hash,
            "rows": rows,
            "summary_report": str(summary_path),
            "validation_report": str(validation_path),
            "idempotency_key": batch_id,
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    append_audit_event(root, log_path=production_spec.audit.log_path, event_type="scoring_batch_completed", actor="argos.system", payload={"batch_id": batch_id, "input_sha256": input_hash, "output_sha256": output_hash, "rows": rows, "model_sha256": selection["model_sha256"]})
    return ScoringResult(batch_id, scored_path, summary, validation, manifest_path, False)
