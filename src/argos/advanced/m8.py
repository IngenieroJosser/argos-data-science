from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.advanced import AdvancedSpec
from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec
from argos.config.production import ProductionSpec
from argos.config.prospective import ProspectiveSpec
from argos.prospective.protocol import verify_frozen_protocol


MATRIX_IMPLEMENTATION = "m8-73-development-matrix-v1"
PIT_IMPLEMENTATION = "m8-73-pit-audit-v1"


@dataclass(frozen=True, slots=True)
class M8MatrixResult:
    artifact: Path
    validation: pd.DataFrame

    @property
    def ready_for_pit_audit(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


@dataclass(frozen=True, slots=True)
class M8PITAuditResult:
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_ablation(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def build_m8_development_matrix(
    *,
    root: Path,
    reports_root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    advanced_spec: AdvancedSpec,
) -> M8MatrixResult:
    from argos.common.duckdb import connect
    from argos.gold.utils import columns_of, copy_query, parquet_source

    base_path = root / modeling_spec.model_matrix
    semantic_path = root / advanced_spec.artifacts.semantic_features
    graph_path = root / advanced_spec.artifacts.graph_features
    anomaly_path = root / advanced_spec.artifacts.anomaly_features
    for path in [base_path, semantic_path, graph_path, anomaly_path]:
        if not path.exists():
            raise FileNotFoundError(f"M8 development matrix requires {path}")

    artifact = root / advanced_spec.artifacts.development_matrix
    con = connect(
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        base = parquet_source(base_path)
        semantic = parquet_source(semantic_path)
        graph = parquet_source(graph_path)
        anomaly = parquet_source(anomaly_path)
        semantic_cols = [c for c in columns_of(con, semantic) if c.startswith("semantic_")]
        graph_cols = [c for c in columns_of(con, graph) if c.startswith("graph_")]
        anomaly_cols = [c for c in columns_of(con, anomaly) if c.startswith("anomaly_")]
        advanced_cols = [*semantic_cols, *graph_cols, *anomaly_cols]
        duplicates = sorted({c for c in advanced_cols if advanced_cols.count(c) > 1})
        if duplicates:
            raise ValueError(f"M8 advanced feature-name collision: {duplicates}")
        split_literals = ",".join(f"'{v}'" for v in advanced_spec.governance.development_splits)
        projection = [
            "b.*",
            *(f's."{c}" AS "{c}"' for c in semantic_cols),
            *(f'g."{c}" AS "{c}"' for c in graph_cols),
            *(f'a."{c}" AS "{c}"' for c in anomaly_cols),
            f"'{advanced_spec.schema_version}' AS _m8_schema_version",
        ]
        copy_query(
            con,
            f"""
            SELECT {', '.join(projection)}
            FROM {base} b
            JOIN {semantic} s USING (contract_id, t0, split)
            JOIN {graph} g USING (contract_id, t0, split)
            JOIN {anomaly} a USING (contract_id, t0, split)
            WHERE b.split IN ({split_literals})
            """,
            artifact,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=True,
        )
        matrix = parquet_source(artifact)
        stats = con.execute(
            f"""
            SELECT COUNT(*) AS rows,
                   COUNT(DISTINCT contract_id) AS distinct_contracts,
                   COUNT(*) FILTER (WHERE {modeling_spec.target} IS NULL) AS null_targets
            FROM {matrix}
            """
        ).fetchdf().iloc[0]
        split_stats = con.execute(
            f"SELECT split, COUNT(*) AS rows FROM {matrix} GROUP BY 1 ORDER BY 1"
        ).fetchdf()
    finally:
        con.close()

    observed_splits = sorted(split_stats["split"].astype(str).tolist())
    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="m8_matrix_grain",
        category="grain",
        passed=int(stats["rows"]) == int(stats["distinct_contracts"]),
        observed={
            "rows": int(stats["rows"]),
            "distinct_contracts": int(stats["distinct_contracts"]),
        },
        requirement="M8 development matrix remains one row per contract",
    )
    add_validation(
        records,
        check_id="m8_matrix_targets_complete",
        category="target",
        passed=int(stats["null_targets"]) == 0,
        observed={"null_targets": int(stats["null_targets"])},
        requirement="M8 development rows retain complete frozen M3 labels",
    )
    add_validation(
        records,
        check_id="m8_matrix_development_splits_only",
        category="evaluation_governance",
        passed=set(observed_splits).issubset(set(advanced_spec.governance.development_splits)),
        observed={"splits": observed_splits},
        requirement="M8 matrix contains only TRAIN/VALIDATION development rows",
    )
    add_validation(
        records,
        check_id="m8_matrix_advanced_families_present",
        category="features",
        passed=bool(semantic_cols and graph_cols and anomaly_cols),
        observed={
            "semantic": len(semantic_cols),
            "graph": len(graph_cols),
            "anomaly": len(anomaly_cols),
        },
        requirement="M8 matrix contains semantic, graph and anomaly feature families",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "advanced" / "73_matrix_validation.parquet")
    return M8MatrixResult(artifact=artifact, validation=validation)


def build_m8_pit_audit(
    *,
    root: Path,
    reports_root: Path,
    manifest_dir: Path,
    modeling_spec: ModelingSpec,
    advanced_spec: AdvancedSpec,
    prospective_spec: ProspectiveSpec,
    production_spec: ProductionSpec,
    docs_root: Path,
) -> M8PITAuditResult:
    from argos.common.duckdb import connect
    from argos.gold.utils import parquet_source

    semantic_path = root / advanced_spec.artifacts.semantic_features
    graph_path = root / advanced_spec.artifacts.graph_features
    anomaly_path = root / advanced_spec.artifacts.anomaly_features
    matrix_path = root / advanced_spec.artifacts.development_matrix
    for path in [semantic_path, graph_path, anomaly_path, matrix_path]:
        if not path.exists():
            raise FileNotFoundError(f"M8 PIT audit requires {path}")

    con = connect()
    try:
        semantic = parquet_source(semantic_path)
        graph = parquet_source(graph_path)
        anomaly = parquet_source(anomaly_path)
        matrix = parquet_source(matrix_path)
        semantic_peer_future = int(
            con.execute(
                f"SELECT COUNT(*) FROM {semantic} "
                "WHERE _pit_semantic_max_peer_t0 IS NOT NULL "
                "AND _pit_semantic_max_peer_t0 >= t0"
            ).fetchone()[0]
        )
        semantic_label_future = int(
            con.execute(
                f"SELECT COUNT(*) FROM {semantic} "
                "WHERE _pit_semantic_max_label_available_at IS NOT NULL "
                "AND _pit_semantic_max_label_available_at >= t0"
            ).fetchone()[0]
        )
        graph_contract_future = int(
            con.execute(
                f"SELECT COUNT(*) FROM {graph} "
                "WHERE _pit_graph_max_contract_t0 IS NOT NULL "
                "AND _pit_graph_max_contract_t0 >= t0"
            ).fetchone()[0]
        )
        graph_cobid_future = int(
            con.execute(
                f"SELECT COUNT(*) FROM {graph} "
                "WHERE _pit_graph_max_cobid_at IS NOT NULL "
                "AND _pit_graph_max_cobid_at >= t0"
            ).fetchone()[0]
        )
        anomaly_non_train_fit = int(
            con.execute(
                f"SELECT COUNT(*) FROM {anomaly} WHERE _anomaly_model_fit_split <> 'train'"
            ).fetchone()[0]
        )
        split_stats = con.execute(
            (
                f"SELECT split, MIN(t0) AS min_t0, MAX(t0) AS max_t0, "
                f"COUNT(*) AS rows FROM {matrix} GROUP BY 1 ORDER BY 1"
            )
        ).fetchdf()
    finally:
        con.close()

    m7_ok, m7_details = verify_frozen_protocol(
        root=root,
        prospective_spec=prospective_spec,
        production_spec=production_spec,
        docs_root=docs_root,
    )
    observed_splits = sorted(split_stats["split"].astype(str).tolist())
    future_violations = {
        "semantic_peer": semantic_peer_future,
        "semantic_label_maturity": semantic_label_future,
        "graph_contract": graph_contract_future,
        "graph_cobid": graph_cobid_future,
    }

    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="m8_semantic_pit_zero_future",
        category="point_in_time",
        passed=(semantic_peer_future + semantic_label_future)
        <= advanced_spec.governance.max_future_feature_violations,
        observed={"peer": semantic_peer_future, "label_maturity": semantic_label_future},
        requirement="semantic peer/history features are strictly point-in-time",
    )
    add_validation(
        records,
        check_id="m8_graph_pit_zero_future",
        category="point_in_time",
        passed=(graph_contract_future + graph_cobid_future)
        <= advanced_spec.governance.max_future_feature_violations,
        observed={"contract_history": graph_contract_future, "cobid_history": graph_cobid_future},
        requirement="graph state contains no same/future relationship observation",
    )
    add_validation(
        records,
        check_id="m8_anomaly_train_only_fit",
        category="evaluation_governance",
        passed=anomaly_non_train_fit == 0,
        observed={"non_train_fit_rows": anomaly_non_train_fit},
        requirement="anomaly model is frozen from TRAIN before VALIDATION scoring",
    )
    add_validation(
        records,
        check_id="m8_consumed_holdout_isolation",
        category="evaluation_governance",
        passed=(
            not advanced_spec.governance.allow_consumed_holdouts_for_selection
            and set(observed_splits).issubset(set(advanced_spec.governance.development_splits))
            and "test" not in observed_splits
        ),
        observed={
            "observed_splits": observed_splits,
            "consumed_holdout_years": list(advanced_spec.governance.consumed_holdout_years),
        },
        requirement="TEST 2025 and OOT 2026 remain unavailable to M8 selection",
    )
    add_validation(
        records,
        check_id="m7_frozen_protocol_integrity",
        category="governance",
        passed=m7_ok,
        observed=m7_details,
        requirement="M8 leaves the frozen M7/ARGOS V1 protocol byte-for-byte intact",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "advanced" / "73_validation.parquet")

    manifest_path = root / advanced_spec.artifacts.pit_manifest
    write_manifest(
        manifest_path,
        {
            "schema_version": advanced_spec.schema_version,
            "implementation": PIT_IMPLEMENTATION,
            "development_matrix": advanced_spec.artifacts.development_matrix,
            "observed_splits": observed_splits,
            "split_stats": split_stats.to_dict(orient="records"),
            "future_feature_violations": future_violations,
            "anomaly_non_train_fit_rows": anomaly_non_train_fit,
            "m7_protocol_verified": m7_ok,
            "m7_protocol_id": m7_details.get("protocol_id"),
            "consumed_test_or_oot_for_selection": False,
        },
    )
    return M8PITAuditResult(validation=validation, manifest_path=manifest_path)
