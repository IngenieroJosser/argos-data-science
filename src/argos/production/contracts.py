from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
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
from argos.production.common import resolve, sha256_file, write_json_atomic

BUILD_IMPLEMENTATION = "m6-51-data-contract-preflight-v1"


@dataclass(frozen=True, slots=True)
class PreflightResult:
    contract_path: Path
    profile: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def build_scoring_contract(
    *,
    root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    production_spec: ProductionSpec,
) -> tuple[Path, dict[str, Any]]:
    feature_contract = load_feature_contract(root, gold_spec, modeling_spec)
    feature_registry_path = resolve(root, production_spec.data_contract.feature_registry)
    registry = pd.read_parquet(feature_registry_path)
    feature_rows = registry.loc[registry["model_role"].astype(str) == "feature"].copy()
    family_by_feature = {
        str(row.feature): str(row.source)
        for row in feature_rows.itertuples(index=False)
        if hasattr(row, "feature") and hasattr(row, "source")
    }
    payload: dict[str, Any] = {
        "schema_version": production_spec.schema_version,
        "model_version": production_spec.core.model_version,
        "id_column": production_spec.data_contract.id_column,
        "t0_column": production_spec.data_contract.t0_column,
        "required_feature_count": len(feature_contract.all_features),
        "features": [
            {
                "name": name,
                "kind": "categorical" if name in set(feature_contract.categorical_features) else "numeric",
                "family": family_by_feature.get(name, "unknown"),
                "nullable": True,
            }
            for name in feature_contract.all_features
        ],
        "forbidden_output_columns": [modeling_spec.target, *production_spec.security.sensitive_columns],
        "deterministic_ranking": list(production_spec.scoring.tie_break),
        "human_review_required": production_spec.core.human_review_required,
        "feature_registry_sha256": sha256_file(feature_registry_path),
    }
    contract_path = resolve(root, production_spec.data_contract.contract_artifact)
    write_json_atomic(contract_path, payload)
    return contract_path, payload


def preflight_parquet(
    input_path: Path,
    *,
    root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    production_spec: ProductionSpec,
    temp_directory: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    contract_path, contract = build_scoring_contract(
        root=root,
        gold_spec=gold_spec,
        modeling_spec=modeling_spec,
        production_spec=production_spec,
    )
    required = [production_spec.data_contract.id_column, production_spec.data_contract.t0_column, *[f["name"] for f in contract["features"]]]
    schema_names = set(pq.ParquetFile(input_path).schema_arrow.names)
    missing_columns = sorted(set(required) - schema_names)
    sensitive_present = sorted(set(production_spec.security.sensitive_columns) & schema_names)

    con = connect(temp_directory=temp_directory, threads=2, memory_limit="8GB")
    try:
        source = f"read_parquet({sql_string(input_path)})"
        stats = con.execute(
            f"""
            SELECT
              COUNT(*) AS row_count,
              COUNT(DISTINCT {production_spec.data_contract.id_column}) AS distinct_ids,
              COUNT(*) FILTER (WHERE {production_spec.data_contract.id_column} IS NULL) AS null_ids,
              COUNT(*) FILTER (WHERE {production_spec.data_contract.t0_column} IS NULL) AS null_t0
            FROM {source}
            """
        ).fetchdf().iloc[0]
    finally:
        con.close()

    profile = pd.DataFrame.from_records(
        [
            {"metric": "row_count", "value": int(stats["row_count"])},
            {"metric": "distinct_ids", "value": int(stats["distinct_ids"])},
            {"metric": "null_ids", "value": int(stats["null_ids"])},
            {"metric": "null_t0", "value": int(stats["null_t0"])},
            {"metric": "required_columns", "value": len(required)},
            {"metric": "missing_columns", "value": len(missing_columns)},
            {"metric": "sensitive_columns_present", "value": len(sensitive_present)},
        ]
    )

    records: list[dict[str, Any]] = []
    add_validation(records, check_id="scoring_contract_feature_count", category="contract", passed=contract["required_feature_count"] >= production_spec.acceptance.min_required_feature_count, observed={"required_feature_count": contract["required_feature_count"], "minimum": production_spec.acceptance.min_required_feature_count}, requirement="production contract carries the complete frozen model feature set")
    add_validation(records, check_id="preflight_required_columns", category="schema", passed=not missing_columns, observed={"missing_columns": missing_columns}, requirement="input batch contains id, t0 and every frozen model feature")
    add_validation(records, check_id="preflight_id_grain", category="grain", passed=(int(stats["row_count"]) == int(stats["distinct_ids"]) and int(stats["null_ids"]) == 0), observed={"rows": int(stats["row_count"]), "distinct_ids": int(stats["distinct_ids"]), "null_ids": int(stats["null_ids"])}, requirement="production scoring input is one non-null row per contract_id")
    add_validation(records, check_id="preflight_t0_present", category="temporal", passed=int(stats["null_t0"]) == 0, observed={"null_t0": int(stats["null_t0"])}, requirement="every scored observation has an explicit prediction timestamp t0")
    add_validation(records, check_id="preflight_sensitive_columns_absent", category="privacy", passed=not sensitive_present, observed={"sensitive_columns_present": sensitive_present}, requirement="production model input does not carry explicitly forbidden sensitive columns")
    validation = pd.DataFrame.from_records(records)
    return profile, validation, contract_path


def build_preflight_evidence(
    *,
    input_path: Path,
    root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    production_spec: ProductionSpec,
    reports_root: Path,
    manifest_dir: Path,
    temp_directory: Path | None = None,
) -> PreflightResult:
    profile, validation, contract_path = preflight_parquet(
        input_path,
        root=root,
        gold_spec=gold_spec,
        modeling_spec=modeling_spec,
        production_spec=production_spec,
        temp_directory=temp_directory,
    )
    write_report(profile, reports_root / "production" / "51_preflight_profile.parquet")
    write_report(validation, reports_root / "production" / "51_validation.parquet")
    append_audit_event(root, log_path=production_spec.audit.log_path, event_type="scoring_preflight", actor="argos.system", payload={"input": str(input_path), "input_sha256": sha256_file(input_path), "contract_sha256": sha256_file(contract_path), "passed": bool(validation.loc[validation["blocking"], "passed"].all())})
    manifest_path = write_manifest(
        manifest_dir / "m6_data_contract_preflight.json",
        {
            "milestone": "M6",
            "component": "51_data_contracts_and_preflight",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": production_spec.schema_version,
            "input": str(input_path),
            "input_sha256": sha256_file(input_path),
            "contract": str(contract_path),
            "contract_sha256": sha256_file(contract_path),
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return PreflightResult(contract_path, profile, validation, manifest_path)
