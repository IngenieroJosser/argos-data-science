from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import quote_identifier, sql_string
from argos.config.gold import GoldSpec
from argos.gold.utils import (
    add_validation,
    columns_of,
    copy_query,
    parquet_source,
    require_columns,
    write_manifest,
)


BUILD_IMPLEMENTATION = "m3-26-pit-audit-v1"


@dataclass(frozen=True, slots=True)
class PITAuditResult:
    artifact: Path
    validation: pd.DataFrame
    feature_registry: pd.DataFrame
    issue_register: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_gate(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _feature_columns(columns: list[str], *, exclude: set[str]) -> list[str]:
    return [
        column
        for column in columns
        if column not in exclude
        and not column.startswith("_pit_")
        and not column.startswith("_gold_")
        and not column.startswith("_source_")
    ]


def build_pit_audit(
    *,
    gold_dir: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> PITAuditResult:
    paths = {
        "labels": gold_dir / "labels" / f"{gold_spec.target.name}.parquet",
        "split": gold_dir / "splits" / "temporal_split.parquet",
        "contract": gold_dir / "features" / "contract_features.parquet",
        "historical": gold_dir / "features" / "historical_features.parquet",
        "competition": gold_dir / "features" / "competition_features.parquet",
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Notebook 26 requires Gold artifacts; missing={missing}")

    artifact = gold_dir / "ml" / "argos_v1.parquet"
    sources = {name: parquet_source(path) for name, path in paths.items()}
    con = connect(
        temp_directory=temp_directory,
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        require_columns(
            con,
            sources["labels"],
            ["contract_id", "t0", gold_spec.target.name],
            label="labels",
        )
        require_columns(
            con,
            sources["split"],
            ["contract_id", "t0", "split", gold_spec.target.name],
            label="split",
        )
        for name in ["contract", "historical", "competition"]:
            require_columns(
                con,
                sources[name],
                ["contract_id", "t0"],
                label=f"{name} features",
            )

        contract_cols = columns_of(con, sources["contract"])
        historical_cols = columns_of(con, sources["historical"])
        competition_cols = columns_of(con, sources["competition"])
        contract_features = _feature_columns(
            contract_cols,
            exclude={"contract_id", "t0", "supplier_code", "entity_id"},
        )
        historical_features = _feature_columns(
            historical_cols,
            exclude={"contract_id", "t0"},
        )
        competition_features = _feature_columns(
            competition_cols,
            exclude={"contract_id", "t0"},
        )

        registry_rows: list[dict[str, Any]] = []
        for feature in contract_features:
            registry_rows.append(
                {
                    "feature": feature,
                    "source": "contract_features",
                    "point_in_time_policy": "conservative signing-time whitelist",
                    "model_role": "feature",
                }
            )
        for feature in historical_features:
            registry_rows.append(
                {
                    "feature": feature,
                    "source": "historical_features",
                    "point_in_time_policy": "strictly-before-t0 history",
                    "model_role": "feature",
                }
            )
        for feature in competition_features:
            registry_rows.append(
                {
                    "feature": feature,
                    "source": "competition_features",
                    "point_in_time_policy": "bidder publication <= t0",
                    "model_role": "feature",
                }
            )
        feature_registry = pd.DataFrame(registry_rows)
        duplicate_feature_names = sorted(
            feature_registry.loc[
                feature_registry["feature"].duplicated(keep=False), "feature"
            ]
            .astype(str)
            .unique()
            .tolist()
        )
        if duplicate_feature_names:
            raise ValueError(
                "Feature-name collision across Gold components: "
                f"{duplicate_feature_names}"
            )

        contract_projection = [
            f"c.{quote_identifier(feature)} AS {quote_identifier(feature)}"
            for feature in contract_features
        ]
        historical_projection = [
            f"h.{quote_identifier(feature)} AS {quote_identifier(feature)}"
            for feature in historical_features
        ]
        competition_projection = [
            f"q.{quote_identifier(feature)} AS {quote_identifier(feature)}"
            for feature in competition_features
        ]
        model_projection = [
            "s.contract_id",
            "s.t0",
            "s.split",
            f"s.{quote_identifier(gold_spec.target.name)} AS {quote_identifier(gold_spec.target.name)}",
            *contract_projection,
            *historical_projection,
            *competition_projection,
            f"{sql_string(gold_spec.schema_version)} AS _gold_schema_version",
        ]
        query = f"""
            SELECT {', '.join(model_projection)}
            FROM {sources['split']} s
            JOIN {sources['contract']} c USING (contract_id)
            JOIN {sources['historical']} h USING (contract_id)
            JOIN {sources['competition']} q USING (contract_id)
            WHERE s.split IN ('train', 'validation', 'test')
        """
        print("[26] materializing audited model matrix from Gold feature components...")
        copy_query(
            con,
            query,
            artifact,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=overwrite,
        )
        matrix = parquet_source(artifact)

        expected_assigned = int(
            con.execute(
                f"SELECT COUNT(*) FROM {sources['split']} WHERE split IN ('train','validation','test')"
            ).fetchone()[0]
        )
        matrix_stats = con.execute(
            f"""
            SELECT
                COUNT(*) AS row_count,
                COUNT(DISTINCT contract_id) AS distinct_contracts,
                COUNT(*) FILTER (WHERE {quote_identifier(gold_spec.target.name)} IS NULL) AS null_labels
            FROM {matrix}
            """
        ).fetchdf().iloc[0]

        # Audit source timestamps carried only as metadata in feature components.
        history_future = int(
            con.execute(
                f"""
                SELECT COUNT(*) FROM {sources['historical']}
                WHERE (_pit_max_supplier_contract_t0 IS NOT NULL AND _pit_max_supplier_contract_t0 >= t0)
                   OR (_pit_max_entity_contract_t0 IS NOT NULL AND _pit_max_entity_contract_t0 >= t0)
                   OR (_pit_max_supplier_entity_contract_t0 IS NOT NULL AND _pit_max_supplier_entity_contract_t0 >= t0)
                   OR (_pit_max_supplier_addition_event_at IS NOT NULL AND _pit_max_supplier_addition_event_at >= t0)
                   OR (_pit_max_supplier_contract_addition_at IS NOT NULL AND _pit_max_supplier_contract_addition_at >= t0)
                   OR (_pit_max_entity_addition_event_at IS NOT NULL AND _pit_max_entity_addition_event_at >= t0)
                   OR (_pit_max_supplier_entity_addition_event_at IS NOT NULL AND _pit_max_supplier_entity_addition_event_at >= t0)
                """
            ).fetchone()[0]
        )
        competition_future = int(
            con.execute(
                f"""
                SELECT COUNT(*) FROM {sources['competition']}
                WHERE _pit_max_bidder_publication_at IS NOT NULL
                  AND _pit_max_bidder_publication_at > t0
                """
            ).fetchone()[0]
        )
        t0_mismatches = int(
            con.execute(
                f"""
                SELECT COUNT(*)
                FROM {sources['split']} s
                JOIN {sources['contract']} c USING (contract_id)
                JOIN {sources['historical']} h USING (contract_id)
                JOIN {sources['competition']} q USING (contract_id)
                WHERE s.split IN ('train','validation','test')
                  AND (s.t0 <> c.t0 OR s.t0 <> h.t0 OR s.t0 <> q.t0)
                """
            ).fetchone()[0]
        )

        matrix_columns = set(columns_of(con, matrix))
        forbidden_present = sorted(
            set(gold_spec.contract_features.forbidden_columns) & matrix_columns
        )
        pit_metadata_present = sorted(
            column for column in matrix_columns if column.startswith("_pit_")
        )

        records: list[dict[str, Any]] = []
        add_validation(
            records,
            check_id="model_matrix_grain",
            category="grain",
            passed=(
                int(matrix_stats["row_count"]) == expected_assigned
                and int(matrix_stats["distinct_contracts"]) == expected_assigned
            ),
            observed={
                "rows": int(matrix_stats["row_count"]),
                "distinct_contracts": int(matrix_stats["distinct_contracts"]),
                "expected_assigned": expected_assigned,
            },
            requirement="one model-matrix row per assigned contract",
        )
        add_validation(
            records,
            check_id="model_matrix_labels_complete",
            category="target",
            passed=int(matrix_stats["null_labels"]) == 0,
            observed={"null_labels": int(matrix_stats["null_labels"])},
            requirement="train/validation/test model rows all have binary labels",
        )
        add_validation(
            records,
            check_id="gold_t0_alignment",
            category="point_in_time",
            passed=t0_mismatches == 0,
            observed={"t0_mismatches": t0_mismatches},
            requirement="all feature components use the same contract t0",
        )
        add_validation(
            records,
            check_id="historical_pit_audit",
            category="point_in_time",
            passed=history_future <= gold_spec.validation.max_feature_future_violations,
            observed={"future_or_same_time_violations": history_future},
            requirement="historical features use only timestamps strictly before t0",
        )
        add_validation(
            records,
            check_id="competition_pit_audit",
            category="point_in_time",
            passed=competition_future <= gold_spec.validation.max_feature_future_violations,
            observed={"future_publication_violations": competition_future},
            requirement="competition features use no bidder observation after t0",
        )
        add_validation(
            records,
            check_id="forbidden_snapshot_fields_absent",
            category="leakage",
            passed=not forbidden_present,
            observed={"forbidden_present": forbidden_present},
            requirement="known mutable/post-t0 Silver snapshot fields are absent from the model matrix",
        )
        add_validation(
            records,
            check_id="pit_audit_metadata_not_features",
            category="leakage",
            passed=not pit_metadata_present,
            observed={"pit_metadata_present": pit_metadata_present},
            requirement="PIT audit timestamps are not exposed as model features",
        )
        add_validation(
            records,
            check_id="feature_registry_nonempty",
            category="features",
            passed=len(feature_registry) >= gold_spec.contract_features.min_selected_features,
            observed={"feature_count": int(len(feature_registry))},
            requirement="audited model feature registry is non-empty and above minimum size",
        )
        validation = pd.DataFrame.from_records(records)

        issue_rows: list[dict[str, Any]] = []
        for row in validation.to_dict(orient="records"):
            if bool(row["passed"]):
                continue
            issue_rows.append(
                {
                    "check_id": row["check_id"],
                    "severity": "blocking" if bool(row["blocking"]) else "warning",
                    "observed": row["observed"],
                    "requirement": row["requirement"],
                    "action": "resolve before M3 gate closure" if bool(row["blocking"]) else "document and monitor",
                }
            )
        issue_register = pd.DataFrame(
            issue_rows,
            columns=["check_id", "severity", "observed", "requirement", "action"],
        )

        write_report(validation, reports_root / "gold" / "26_pit_validation.parquet")
        write_report(feature_registry, reports_root / "gold" / "26_feature_registry.parquet")
        write_report(issue_register, reports_root / "gold" / "m3_issue_register.parquet")
    finally:
        con.close()

    manifest_path = write_manifest(
        manifest_dir / "gold_pit_audit.json",
        {
            "milestone": "M3",
            "component": "26_gold_point_in_time_audit",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": gold_spec.schema_version,
            "artifact": str(artifact),
            "feature_count": int(len(feature_registry)),
            "blocking_validation_passed": bool(
                validation.loc[validation["blocking"], "passed"].all()
            ),
        },
    )
    return PITAuditResult(
        artifact,
        validation,
        feature_registry,
        issue_register,
        manifest_path,
    )
