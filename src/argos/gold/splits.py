from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import sql_string
from argos.config.gold import GoldSpec
from argos.gold.utils import add_validation, copy_query, parquet_source, require_columns, write_manifest


BUILD_IMPLEMENTATION = "m3-21-temporal-split-v1"


@dataclass(frozen=True, slots=True)
class SplitBuildResult:
    artifact: Path
    validation: pd.DataFrame
    summary: pd.DataFrame
    by_year: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def build_temporal_splits(
    *,
    gold_dir: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> SplitBuildResult:
    labels_path = gold_dir / "labels" / f"{gold_spec.target.name}.parquet"
    if not labels_path.exists():
        raise FileNotFoundError("Run notebook 20 first: Gold labels are missing")
    split_path = gold_dir / "splits" / "temporal_split.parquet"
    labels = parquet_source(labels_path)
    con = connect(
        temp_directory=temp_directory,
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        require_columns(
            con,
            labels,
            ["contract_id", "t0", "eligible", gold_spec.target.name],
            label="Gold labels",
        )
        s = gold_spec.splits
        query = f"""
            SELECT
                contract_id,
                t0,
                {gold_spec.target.name},
                eligible,
                CASE
                    WHEN NOT eligible THEN 'not_eligible'
                    WHEN CAST(t0 AS DATE) BETWEEN DATE {sql_string(s.train_start.isoformat())} AND DATE {sql_string(s.train_end.isoformat())}
                        THEN 'train'
                    WHEN CAST(t0 AS DATE) BETWEEN DATE {sql_string(s.validation_start.isoformat())} AND DATE {sql_string(s.validation_end.isoformat())}
                        THEN 'validation'
                    WHEN CAST(t0 AS DATE) BETWEEN DATE {sql_string(s.test_start.isoformat())} AND DATE {sql_string(s.test_end.isoformat())}
                        THEN 'test'
                    ELSE 'eligible_out_of_split'
                END AS split,
                {sql_string(gold_spec.schema_version)} AS _gold_schema_version
            FROM {labels}
        """
        print("[21] materializing frozen chronological split assignments...")
        copy_query(
            con,
            query,
            split_path,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=overwrite,
        )
        split = parquet_source(split_path)
        summary = con.execute(
            f"""
            SELECT
                split,
                COUNT(*) AS row_count,
                COUNT(*) FILTER (WHERE {gold_spec.target.name}=1) AS positives,
                COUNT(*) FILTER (WHERE {gold_spec.target.name}=0) AS negatives,
                MIN(t0) AS min_t0,
                MAX(t0) AS max_t0,
                CASE WHEN COUNT(*) FILTER (WHERE {gold_spec.target.name} IS NOT NULL)=0 THEN NULL
                     ELSE COUNT(*) FILTER (WHERE {gold_spec.target.name}=1)::DOUBLE /
                          COUNT(*) FILTER (WHERE {gold_spec.target.name} IS NOT NULL)
                END AS prevalence
            FROM {split}
            GROUP BY split
            ORDER BY CASE split WHEN 'train' THEN 1 WHEN 'validation' THEN 2 WHEN 'test' THEN 3 ELSE 4 END, split
            """
        ).fetchdf()
        by_year = con.execute(
            f"""
            SELECT
                EXTRACT(YEAR FROM t0)::INTEGER AS t0_year,
                split,
                COUNT(*) AS row_count,
                COUNT(*) FILTER (WHERE {gold_spec.target.name}=1) AS positives,
                COUNT(*) FILTER (WHERE {gold_spec.target.name}=0) AS negatives
            FROM {split}
            WHERE t0 IS NOT NULL
            GROUP BY 1,2
            ORDER BY 1,2
            """
        ).fetchdf()

        def row_for(name: str) -> pd.Series | None:
            rows = summary.loc[summary["split"] == name]
            return None if rows.empty else rows.iloc[0]

        train = row_for("train")
        validation = row_for("validation")
        test = row_for("test")
        records: list[dict[str, Any]] = []
        add_validation(
            records,
            check_id="split_periods_ordered",
            category="temporal",
            passed=(s.train_end < s.validation_start <= s.validation_end < s.test_start),
            observed={
                "train": [s.train_start.isoformat(), s.train_end.isoformat()],
                "validation": [s.validation_start.isoformat(), s.validation_end.isoformat()],
                "test": [s.test_start.isoformat(), s.test_end.isoformat()],
            },
            requirement="train < validation < test with no temporal overlap",
        )
        requirements = {
            "train": (train, s.min_train_rows),
            "validation": (validation, s.min_validation_rows),
            "test": (test, s.min_test_rows),
        }
        for name, (row, minimum) in requirements.items():
            rows = 0 if row is None else int(row["row_count"])
            positives = 0 if row is None else int(row["positives"])
            negatives = 0 if row is None else int(row["negatives"])
            add_validation(
                records,
                check_id=f"{name}_population_sufficient",
                category="split",
                passed=(rows >= minimum and positives >= s.min_positive_rows_per_split and negatives > 0),
                observed={"rows": rows, "positives": positives, "negatives": negatives},
                requirement=(
                    f"{name} has >= {minimum} rows, >= {s.min_positive_rows_per_split} positives and nonzero negatives"
                ),
            )
        assigned_unlabeled = int(
            con.execute(
                f"SELECT COUNT(*) FROM {split} WHERE split IN ('train','validation','test') AND {gold_spec.target.name} IS NULL"
            ).fetchone()[0]
        )
        add_validation(
            records,
            check_id="assigned_rows_labeled",
            category="target",
            passed=assigned_unlabeled == 0,
            observed={"assigned_unlabeled": assigned_unlabeled},
            requirement="all train/validation/test rows are eligible and labeled",
        )
        duplicate_rows = int(
            con.execute(
                f"SELECT COALESCE(SUM(n-1),0)::BIGINT FROM (SELECT contract_id, COUNT(*) AS n FROM {split} GROUP BY contract_id HAVING COUNT(*)>1)"
            ).fetchone()[0]
        )
        add_validation(
            records,
            check_id="split_grain_unique",
            category="grain",
            passed=duplicate_rows == 0,
            observed={"duplicate_excess_rows": duplicate_rows},
            requirement="one split assignment per contract",
        )
        test_after_validation = bool(
            test is not None and validation is not None and pd.Timestamp(test["min_t0"]) > pd.Timestamp(validation["max_t0"])
        )
        add_validation(
            records,
            check_id="test_strictly_future",
            category="temporal",
            passed=test_after_validation,
            observed={
                "validation_max_t0": None if validation is None else str(validation["max_t0"]),
                "test_min_t0": None if test is None else str(test["min_t0"]),
            },
            requirement="test period starts strictly after validation ends",
        )
        validation_frame = pd.DataFrame.from_records(records)
        write_report(validation_frame, reports_root / "gold" / "21_split_validation.parquet")
        write_report(summary, reports_root / "gold" / "21_split_summary.parquet")
        write_report(by_year, reports_root / "gold" / "21_split_by_year.parquet")
    finally:
        con.close()

    manifest_path = write_manifest(
        manifest_dir / "gold_temporal_split.json",
        {
            "milestone": "M3",
            "component": "21_temporal_split_design",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": gold_spec.schema_version,
            "target_name": gold_spec.target.name,
            "artifact": str(split_path),
            "periods": {
                "train": [s.train_start.isoformat(), s.train_end.isoformat()],
                "validation": [s.validation_start.isoformat(), s.validation_end.isoformat()],
                "test": [s.test_start.isoformat(), s.test_end.isoformat()],
            },
            "blocking_validation_passed": bool(
                validation_frame.loc[validation_frame["blocking"], "passed"].all()
            ),
        },
    )
    return SplitBuildResult(split_path, validation_frame, summary, by_year, manifest_path)
