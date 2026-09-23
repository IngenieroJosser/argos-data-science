from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import sql_string
from argos.config.silver import SilverSpec
from argos.silver.utils import add_validation, write_manifest


BUILD_IMPLEMENTATION = "m2-14-cross-silver-validation-v2"


@dataclass(frozen=True, slots=True)
class SilverValidationResult:
    validation: pd.DataFrame
    issues: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_gate(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


EXPECTED_ARTIFACTS = (
    "contracts.parquet",
    "contracts_snapshot_state.parquet",
    "process_versions.parquet",
    "processes.parquet",
    "contract_process_links.parquet",
    "suppliers.parquet",
    "bidder_participations.parquet",
    "procedure_process_map.parquet",
    "bidder_process_links.parquet",
    "addition_event_versions.parquet",
    "addition_events.parquet",
    "bidder_supplier_entity_map.parquet",
)

EXPECTED_COMPONENT_REPORTS = (
    "10_validation.parquet",
    "11_validation.parquet",
    "12_validation.parquet",
    "13_validation.parquet",
)

EXPECTED_MANIFESTS = (
    "silver_contracts_processes.json",
    "silver_suppliers_bidders.json",
    "silver_events.json",
    "silver_entity_resolution.json",
)


def _component_validation(reports_root: Path) -> tuple[bool, dict[str, Any]]:
    observed: dict[str, Any] = {}
    all_ok = True
    for name in EXPECTED_COMPONENT_REPORTS:
        path = reports_root / "silver" / name
        if not path.exists():
            observed[name] = "missing"
            all_ok = False
            continue
        frame = pd.read_parquet(path)
        blocking = frame.loc[frame["blocking"]]
        ok = bool(not blocking.empty and blocking["passed"].all())
        observed[name] = {
            "blocking": int(len(blocking)),
            "passed": int(blocking["passed"].sum()) if not blocking.empty else 0,
            "ok": ok,
        }
        all_ok = all_ok and ok
    return all_ok, observed


def _schema_version_check(con, silver_dir: Path, expected: str) -> tuple[bool, dict[str, Any]]:
    observed: dict[str, Any] = {}
    ok = True
    for name in EXPECTED_ARTIFACTS:
        path = silver_dir / name
        if not path.exists():
            observed[name] = "missing"
            ok = False
            continue
        source = f"read_parquet({sql_string(path)})"
        columns = set(
            con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()["column_name"].astype(str)
        )
        if "_silver_schema_version" not in columns:
            observed[name] = "missing _silver_schema_version"
            ok = False
            continue
        versions = {
            str(row[0])
            for row in con.execute(
                f"SELECT DISTINCT _silver_schema_version FROM {source} "
                "WHERE _silver_schema_version IS NOT NULL LIMIT 3"
            ).fetchall()
        }
        observed[name] = sorted(versions)
        if versions != {expected}:
            ok = False
    return ok, observed


def _deferred_scope(project_config_path: Path) -> tuple[bool, dict[str, Any]]:
    if not project_config_path.exists():
        return False, {"error": "project.toml missing"}
    with project_config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    scope = raw.get("m1_scope", {})
    datasets = set(scope.get("deferred_datasets", []))
    relationships = set(scope.get("deferred_relationships", []))
    ok = {"payments", "sanctions"}.issubset(datasets) and "bidders_suppliers" in relationships
    return ok, {
        "deferred_datasets": sorted(datasets),
        "deferred_relationships": sorted(relationships),
    }


def validate_silver_m2(
    *,
    reports_root: Path,
    silver_dir: Path,
    manifest_dir: Path,
    project_config_path: Path,
    silver_spec: SilverSpec,
    temp_directory: Path | None = None,
) -> SilverValidationResult:
    records: list[dict[str, Any]] = []

    missing_artifacts = [name for name in EXPECTED_ARTIFACTS if not (silver_dir / name).exists()]
    add_validation(
        records,
        check_id="silver_artifacts_complete",
        category="artifacts",
        passed=not missing_artifacts,
        observed={"missing": missing_artifacts, "expected_count": len(EXPECTED_ARTIFACTS)},
        requirement="all canonical M2 Silver artifacts from notebooks 10–13 exist",
    )

    missing_manifests = [name for name in EXPECTED_MANIFESTS if not (manifest_dir / name).exists()]
    add_validation(
        records,
        check_id="component_manifests_complete",
        category="lineage",
        passed=not missing_manifests,
        observed={"missing": missing_manifests},
        requirement="notebooks 10–13 persist their lineage manifests",
    )

    component_ok, component_observed = _component_validation(reports_root)
    add_validation(
        records,
        check_id="component_blocking_checks",
        category="component_validation",
        passed=component_ok,
        observed=component_observed,
        requirement="every blocking validation from notebooks 10–13 passes",
    )

    con = connect(
        temp_directory=temp_directory,
        threads=silver_spec.runtime.duckdb_threads,
        memory_limit=silver_spec.runtime.duckdb_memory_limit,
    )
    try:
        if not missing_artifacts:
            schema_ok, schema_observed = _schema_version_check(
                con, silver_dir, silver_spec.schema_version
            )
            add_validation(
                records,
                check_id="silver_schema_version_consistent",
                category="lineage",
                passed=schema_ok,
                observed=schema_observed,
                requirement=f"every Silver artifact declares schema {silver_spec.schema_version}",
            )

            contracts = f"read_parquet({sql_string(silver_dir / 'contracts.parquet')})"
            suppliers = f"read_parquet({sql_string(silver_dir / 'suppliers.parquet')})"
            contract_supplier = con.execute(
                f"""
                SELECT
                    COUNT(*) AS contracts,
                    COUNT(*) FILTER (WHERE c.supplier_code IS NOT NULL) AS with_supplier_code,
                    COUNT(*) FILTER (WHERE s.supplier_code IS NOT NULL) AS matched
                FROM {contracts} c
                LEFT JOIN {suppliers} s USING (supplier_code)
                """
            ).fetchdf().iloc[0]
            coverage = (
                int(contract_supplier["matched"]) / int(contract_supplier["contracts"])
                if int(contract_supplier["contracts"])
                else 0.0
            )
            add_validation(
                records,
                check_id="contract_supplier_cross_coverage",
                category="relationships",
                passed=coverage >= 0.90,
                observed={
                    "coverage": coverage,
                    "matched": int(contract_supplier["matched"]),
                    "contracts": int(contract_supplier["contracts"]),
                    "with_supplier_code": int(contract_supplier["with_supplier_code"]),
                },
                requirement="canonical contract→supplier coverage >= 90% with no supplier-side expansion",
            )

            bidder_links = f"read_parquet({sql_string(silver_dir / 'bidder_process_links.parquet')})"
            entity_map = f"read_parquet({sql_string(silver_dir / 'bidder_supplier_entity_map.parquet')})"
            er_join = con.execute(
                f"""
                SELECT
                    COUNT(*) AS link_rows,
                    COUNT(DISTINCT l.bidder_process_link_id) AS distinct_link_ids,
                    COUNT(*) FILTER (WHERE m.bidder_key IS NULL) AS missing_entity_map
                FROM {bidder_links} l
                LEFT JOIN {entity_map} m USING (bidder_key)
                """
            ).fetchdf().iloc[0]
            add_validation(
                records,
                check_id="bidder_entity_map_complete",
                category="entity_resolution",
                passed=(
                    int(er_join["link_rows"]) == int(er_join["distinct_link_ids"])
                    and int(er_join["missing_entity_map"]) == 0
                ),
                observed={
                    "link_rows": int(er_join["link_rows"]),
                    "distinct_link_ids": int(er_join["distinct_link_ids"]),
                    "missing_entity_map": int(er_join["missing_entity_map"]),
                },
                requirement="every bidder-process link has exactly one bidder entity-resolution record",
            )

            events = f"read_parquet({sql_string(silver_dir / 'addition_events.parquet')})"
            event_contract = con.execute(
                f"""
                SELECT
                    COUNT(*) AS events,
                    COUNT(*) FILTER (WHERE contract_link_status = 'matched') AS matched,
                    COUNT(DISTINCT event_id) AS distinct_event_ids
                FROM {events}
                """
            ).fetchdf().iloc[0]
            event_coverage = (
                int(event_contract["matched"]) / int(event_contract["events"])
                if int(event_contract["events"])
                else 0.0
            )
            add_validation(
                records,
                check_id="event_contract_cross_integrity",
                category="relationships",
                passed=(
                    int(event_contract["events"]) == int(event_contract["distinct_event_ids"])
                    and event_coverage >= silver_spec.validation.additions_contracts_min_coverage
                ),
                observed={
                    "events": int(event_contract["events"]),
                    "distinct_event_ids": int(event_contract["distinct_event_ids"]),
                    "contract_coverage": event_coverage,
                },
                requirement="addition event grain remains unique and contract linkage clears the M1 threshold",
            )
    finally:
        con.close()

    deferred_ok, deferred_observed = _deferred_scope(project_config_path)
    add_validation(
        records,
        check_id="deferred_sources_remain_explicit",
        category="scope",
        passed=deferred_ok,
        observed=deferred_observed,
        requirement="payments and sanctions remain explicit deferred sources; bidder→supplier was resolved in notebook 13",
    )

    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "silver" / "m2_validation.parquet")

    issue_records: list[dict[str, Any]] = []
    for row in validation.loc[~validation["passed"]].to_dict(orient="records"):
        issue_records.append(
            {
                "check_id": row["check_id"],
                "category": row["category"],
                "severity": "blocking" if row["blocking"] else "warning",
                "observed": row["observed"],
                "requirement": row["requirement"],
                "action": "resolve_before_m2_close" if row["blocking"] else "document_and_monitor",
            }
        )
    issues = pd.DataFrame.from_records(
        issue_records,
        columns=["check_id", "category", "severity", "observed", "requirement", "action"],
    )
    write_report(issues, reports_root / "silver" / "m2_issue_register.parquet")

    manifest_path = write_manifest(
        manifest_dir / "silver_m2_validation.json",
        {
            "milestone": "M2",
            "component": "14_silver_validation",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": silver_spec.schema_version,
            "blocking_validation_passed": bool(
                validation.loc[validation["blocking"], "passed"].all()
            ),
            "issue_count": int(len(issues)),
            "blocking_issue_count": int(
                (issues["severity"] == "blocking").sum() if not issues.empty else 0
            ),
        },
    )
    return SilverValidationResult(validation, issues, manifest_path)
