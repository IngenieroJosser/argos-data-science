from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import sql_string
from argos.common.validation import add_validation, write_manifest
from argos.config.production import ProductionSpec
from argos.production.audit import append_audit_event
from argos.production.common import resolve, sha256_file

BUILD_IMPLEMENTATION = "m6-54-human-review-audit-v1"
ALLOWED_REVIEW_STATUSES = ("pending", "in_review", "reviewed", "dismissed", "escalated")


@dataclass(frozen=True, slots=True)
class ReviewQueueResult:
    queue_path: Path
    queue_summary: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def build_review_queue(
    *,
    scored_path: Path,
    root: Path,
    production_spec: ProductionSpec,
    reports_root: Path,
    manifest_dir: Path,
    temp_directory: Path | None = None,
) -> ReviewQueueResult:
    queue_root = resolve(root, production_spec.scoring.queue_root)
    queue_root.mkdir(parents=True, exist_ok=True)
    queue_path = queue_root / f"{scored_path.stem}.parquet"
    con = connect(temp_directory=temp_directory, threads=2, memory_limit="8GB")
    try:
        tmp = queue_path.with_suffix(".parquet.tmp")
        query = f"""
            SELECT
              contract_id,
              t0,
              score AS model_score,
              raw_score AS model_raw_score,
              rank AS model_rank,
              model_version,
              scoring_batch_id,
              'pending' AS review_status,
              NULL::VARCHAR AS reviewer_id,
              NULL::VARCHAR AS review_outcome,
              NULL::VARCHAR AS review_notes,
              NULL::TIMESTAMP AS reviewed_at
            FROM read_parquet({sql_string(scored_path)})
            WHERE review_priority
            ORDER BY model_rank
        """
        con.execute(f"COPY ({query}) TO {sql_string(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD)")
        tmp.replace(queue_path)
        stats = con.execute(f"SELECT COUNT(*) AS row_count, COUNT(DISTINCT contract_id) AS distinct_ids, MIN(model_rank) AS min_rank, MAX(model_rank) AS max_rank FROM read_parquet({sql_string(queue_path)})").fetchdf().iloc[0]
    finally:
        con.close()

    queue_summary = pd.DataFrame.from_records([{"batch_id": scored_path.stem, "rows": int(stats["row_count"]), "distinct_contracts": int(stats["distinct_ids"]), "min_rank": int(stats["min_rank"]), "max_rank": int(stats["max_rank"]), "review_status": "pending"}])
    write_report(queue_summary, reports_root / "production" / "54_review_queue_summary.parquet")

    cols = set(pd.read_parquet(queue_path, columns=None).columns)
    sensitive = set(production_spec.security.sensitive_columns)
    records: list[dict[str, Any]] = []
    add_validation(records, check_id="review_queue_nonempty", category="human_review", passed=int(stats["row_count"]) > 0 and int(stats["row_count"]) == int(stats["distinct_ids"]), observed=queue_summary.iloc[0].to_dict(), requirement="operational top-K ranking materializes a unique non-empty human review queue")
    add_validation(records, check_id="review_queue_separates_model_and_human_fields", category="governance", passed={"model_score", "model_raw_score", "model_rank", "review_status", "review_outcome"}.issubset(cols), observed={"columns": sorted(cols)}, requirement="model evidence remains distinct from subsequent human review decisions")
    add_validation(records, check_id="review_queue_initial_state", category="workflow", passed=queue_summary.iloc[0]["review_status"] == "pending", observed={"allowed_statuses": list(ALLOWED_REVIEW_STATUSES), "initial": "pending"}, requirement="model prioritization creates pending reviews; it does not create legal or enforcement outcomes")
    add_validation(records, check_id="review_queue_privacy_minimized", category="privacy", passed=not (cols & sensitive), observed={"sensitive_present": sorted(cols & sensitive)}, requirement="review queue carries only identifiers, scores, ranking metadata and explicit human-review fields")
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "production" / "54_validation.parquet")

    append_audit_event(root, log_path=production_spec.audit.log_path, event_type="review_queue_materialized", actor="argos.system", payload={"batch_id": scored_path.stem, "queue_sha256": sha256_file(queue_path), "rows": int(stats["row_count"]), "initial_status": "pending"})
    manifest_path = write_manifest(manifest_dir / "m6_human_review_queue.json", {"milestone": "M6", "component": "54_human_review_and_audit", "implementation": BUILD_IMPLEMENTATION, "schema_version": production_spec.schema_version, "queue": str(queue_path), "queue_sha256": sha256_file(queue_path), "rows": int(stats["row_count"]), "autonomous_decision": False, "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all())})
    return ReviewQueueResult(queue_path, queue_summary, validation, manifest_path)
