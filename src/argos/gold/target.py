from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import sql_string
from argos.config.gold import GoldSpec
from argos.gold.utils import (
    add_validation,
    copy_query,
    parquet_source,
    require_columns,
    sql_list,
    write_manifest,
)


BUILD_IMPLEMENTATION = "m3-20-target-engineering-v1"


@dataclass(frozen=True, slots=True)
class TargetBuildResult:
    artifacts: dict[str, Path]
    validation: pd.DataFrame
    by_year: pd.DataFrame
    event_scope: pd.DataFrame
    censoring: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _artifact_paths(gold_dir: Path, target_name: str) -> dict[str, Path]:
    return {
        "target_population": gold_dir / "target_population.parquet",
        "labels": gold_dir / "labels" / f"{target_name}.parquet",
    }


def build_target_gold(
    *,
    silver_dir: Path,
    gold_dir: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> TargetBuildResult:
    """Freeze and materialize the M3 V1 target with explicit censoring.

    The target is built only from canonical M2 Silver contracts/events. No
    current-state contract snapshot fields are consulted.
    """
    contracts_path = silver_dir / "contracts.parquet"
    events_path = silver_dir / "addition_events.parquet"
    if not contracts_path.exists() or not events_path.exists():
        raise FileNotFoundError(
            "Notebook 20 requires contracts.parquet and addition_events.parquet from closed M2"
        )

    artifacts = _artifact_paths(gold_dir, gold_spec.target.name)
    contracts = parquet_source(contracts_path)
    events = parquet_source(events_path)
    con = connect(
        temp_directory=temp_directory,
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        require_columns(
            con,
            contracts,
            ["contract_id", gold_spec.target.t0_column, "_silver_schema_version"],
            label="contracts.parquet",
        )
        require_columns(
            con,
            events,
            ["event_id", "contract_id", "event_at", "event_type", "contract_link_status"],
            label="addition_events.parquet",
        )

        label_cutoff = con.execute(
            f"SELECT MAX(event_at) FROM {events} WHERE event_at IS NOT NULL"
        ).fetchone()[0]
        if label_cutoff is None:
            raise ValueError("Cannot construct target: addition_events has no parsed event_at")

        target = gold_spec.target
        included = sql_list(target.included_event_types)
        horizon = int(target.horizon_days)
        population_query = f"""
            WITH base AS (
                SELECT
                    contract_id,
                    CAST({target.t0_column} AS TIMESTAMP) AS t0
                FROM {contracts}
            )
            SELECT
                contract_id,
                t0,
                t0 + INTERVAL '{horizon} days' AS window_end,
                CAST({sql_string(str(label_cutoff))} AS TIMESTAMP) AS label_cutoff,
                {horizon}::INTEGER AS horizon_days,
                CASE
                    WHEN t0 IS NULL THEN 'missing_t0'
                    WHEN EXTRACT(YEAR FROM t0) NOT BETWEEN {target.plausible_year_min} AND {target.plausible_year_max}
                        THEN 'implausible_t0'
                    WHEN t0 > CAST({sql_string(str(label_cutoff))} AS TIMESTAMP) THEN 't0_after_label_cutoff'
                    WHEN t0 + INTERVAL '{horizon} days' > CAST({sql_string(str(label_cutoff))} AS TIMESTAMP)
                        THEN 'right_censored'
                    ELSE 'eligible'
                END AS population_status,
                (
                    t0 IS NOT NULL
                    AND EXTRACT(YEAR FROM t0) BETWEEN {target.plausible_year_min} AND {target.plausible_year_max}
                    AND t0 <= CAST({sql_string(str(label_cutoff))} AS TIMESTAMP)
                    AND t0 + INTERVAL '{horizon} days' <= CAST({sql_string(str(label_cutoff))} AS TIMESTAMP)
                ) AS eligible,
                (
                    t0 IS NOT NULL
                    AND t0 <= CAST({sql_string(str(label_cutoff))} AS TIMESTAMP)
                    AND t0 + INTERVAL '{horizon} days' > CAST({sql_string(str(label_cutoff))} AS TIMESTAMP)
                ) AS censored,
                {sql_string(gold_spec.schema_version)} AS _gold_schema_version
            FROM base
        """
        print("[20] materializing target population and censoring state...")
        copy_query(
            con,
            population_query,
            artifacts["target_population"],
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=overwrite,
        )

        population = parquet_source(artifacts["target_population"])
        labels_query = f"""
            WITH qualifying AS (
                SELECT
                    p.contract_id,
                    MIN(e.event_at) AS first_qualifying_event_at,
                    COUNT(*)::BIGINT AS qualifying_event_count_180d
                FROM {population} p
                JOIN {events} e USING (contract_id)
                WHERE p.t0 IS NOT NULL
                  AND e.contract_link_status = 'matched'
                  AND e.event_at IS NOT NULL
                  AND UPPER(TRIM(e.event_type)) IN ({included})
                  AND e.event_at > p.t0
                  AND e.event_at <= p.window_end
                GROUP BY p.contract_id
            )
            SELECT
                p.contract_id,
                p.t0,
                p.window_end,
                p.label_cutoff,
                p.horizon_days,
                p.population_status,
                p.eligible,
                p.censored,
                CASE
                    WHEN NOT p.eligible THEN NULL
                    WHEN q.contract_id IS NOT NULL THEN 1
                    ELSE 0
                END::TINYINT AS {gold_spec.target.name},
                q.first_qualifying_event_at,
                CASE
                    WHEN q.first_qualifying_event_at IS NULL THEN NULL
                    ELSE DATE_DIFF('day', p.t0, q.first_qualifying_event_at)
                END::INTEGER AS days_to_first_qualifying_event,
                COALESCE(q.qualifying_event_count_180d, 0)::BIGINT AS qualifying_event_count_180d,
                {sql_string(','.join(target.included_event_types))} AS target_event_scope,
                {sql_string(gold_spec.schema_version)} AS _gold_schema_version
            FROM {population} p
            LEFT JOIN qualifying q USING (contract_id)
        """
        print("[20] materializing labels from future qualifying events only...")
        copy_query(
            con,
            labels_query,
            artifacts["labels"],
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=overwrite,
        )

        labels = parquet_source(artifacts["labels"])
        stats = con.execute(
            f"""
            SELECT
                COUNT(*) AS row_count,
                COUNT(DISTINCT contract_id) AS distinct_contracts,
                COUNT(*) FILTER (WHERE t0 IS NOT NULL) AS with_t0,
                COUNT(*) FILTER (WHERE eligible) AS eligible_rows,
                COUNT(*) FILTER (WHERE censored) AS censored_rows,
                COUNT(*) FILTER (WHERE {gold_spec.target.name} = 1) AS positives,
                COUNT(*) FILTER (WHERE {gold_spec.target.name} = 0) AS negatives,
                COUNT(*) FILTER (WHERE {gold_spec.target.name} IS NULL) AS null_labels
            FROM {labels}
            """
        ).fetchdf().iloc[0]
        total = int(stats["row_count"])
        eligible = int(stats["eligible_rows"])
        positives = int(stats["positives"])
        negatives = int(stats["negatives"])
        prevalence = positives / eligible if eligible else 0.0
        t0_coverage = int(stats["with_t0"]) / total if total else 0.0

        event_scope = con.execute(
            f"""
            SELECT
                COALESCE(event_type, '<NULL>') AS event_type,
                COUNT(*) AS canonical_events,
                COUNT(DISTINCT contract_id) AS distinct_contracts,
                MIN(event_at) AS min_event_at,
                MAX(event_at) AS max_event_at,
                COALESCE(UPPER(TRIM(event_type)) IN ({included}), FALSE) AS included_in_target
            FROM {events}
            GROUP BY event_type
            ORDER BY canonical_events DESC, event_type
            """
        ).fetchdf()

        by_year = con.execute(
            f"""
            SELECT
                EXTRACT(YEAR FROM t0)::INTEGER AS t0_year,
                COUNT(*) FILTER (WHERE eligible) AS eligible,
                COUNT(*) FILTER (WHERE {gold_spec.target.name} = 1) AS positives,
                COUNT(*) FILTER (WHERE {gold_spec.target.name} = 0) AS negatives,
                CASE
                    WHEN COUNT(*) FILTER (WHERE eligible) = 0 THEN NULL
                    ELSE COUNT(*) FILTER (WHERE {gold_spec.target.name} = 1)::DOUBLE
                         / COUNT(*) FILTER (WHERE eligible)
                END AS prevalence
            FROM {labels}
            WHERE t0 IS NOT NULL
            GROUP BY 1
            ORDER BY 1
            """
        ).fetchdf()

        censoring = con.execute(
            f"""
            SELECT population_status, COUNT(*) AS contracts
            FROM {population}
            GROUP BY population_status
            ORDER BY contracts DESC
            """
        ).fetchdf()

        validation_records: list[dict[str, Any]] = []
        add_validation(
            validation_records,
            check_id="target_grain_unique",
            category="grain",
            passed=total == int(stats["distinct_contracts"]),
            observed={"rows": total, "distinct_contracts": int(stats["distinct_contracts"])},
            requirement="one Gold target row per contract_id",
        )
        add_validation(
            validation_records,
            check_id="t0_coverage",
            category="temporal",
            passed=t0_coverage >= target.min_t0_coverage,
            observed={"coverage": t0_coverage, "with_t0": int(stats["with_t0"]), "rows": total},
            requirement=f"t0 coverage >= {target.min_t0_coverage:.2%}",
        )
        implausible_t0 = int(
            con.execute(
                f"SELECT COUNT(*) FROM {population} WHERE population_status = 'implausible_t0'"
            ).fetchone()[0]
        )
        add_validation(
            validation_records,
            check_id="t0_plausible",
            category="temporal",
            passed=implausible_t0 == 0,
            observed={
                "implausible_t0": implausible_t0,
                "plausible_year_min": target.plausible_year_min,
                "plausible_year_max": target.plausible_year_max,
            },
            requirement="all parsed t0 values used by Gold fall inside the configured plausible year range",
        )
        included_present = int(event_scope.loc[event_scope["included_in_target"], "canonical_events"].sum())
        add_validation(
            validation_records,
            check_id="event_scope_explicit_and_nonempty",
            category="target_semantics",
            passed=included_present > 0,
            observed={"included_event_types": list(target.included_event_types), "canonical_events": included_present},
            requirement="configured target event types exist in canonical Silver events",
        )
        future_violations = int(
            con.execute(
                f"SELECT COUNT(*) FROM {labels} WHERE first_qualifying_event_at IS NOT NULL AND first_qualifying_event_at <= t0"
            ).fetchone()[0]
        )
        horizon_violations = int(
            con.execute(
                f"SELECT COUNT(*) FROM {labels} WHERE first_qualifying_event_at IS NOT NULL AND first_qualifying_event_at > window_end"
            ).fetchone()[0]
        )
        add_validation(
            validation_records,
            check_id="future_events_only",
            category="point_in_time",
            passed=future_violations == 0,
            observed={"violations": future_violations},
            requirement="every qualifying target event occurs strictly after t0",
        )
        add_validation(
            validation_records,
            check_id="horizon_exact",
            category="point_in_time",
            passed=horizon_violations == 0,
            observed={"horizon_days": horizon, "violations": horizon_violations},
            requirement=f"qualifying events are within (t0, t0+{horizon}d]",
        )
        censored_labeled = int(
            con.execute(
                f"SELECT COUNT(*) FROM {labels} WHERE censored AND {gold_spec.target.name} IS NOT NULL"
            ).fetchone()[0]
        )
        invalid_eligible_labels = int(
            con.execute(
                f"SELECT COUNT(*) FROM {labels} WHERE eligible AND {gold_spec.target.name} NOT IN (0, 1)"
            ).fetchone()[0]
        )
        noneligible_labeled = int(
            con.execute(
                f"SELECT COUNT(*) FROM {labels} WHERE NOT eligible AND {gold_spec.target.name} IS NOT NULL"
            ).fetchone()[0]
        )
        add_validation(
            validation_records,
            check_id="censoring_correct",
            category="censoring",
            passed=censored_labeled == 0,
            observed={"censored_rows": int(stats["censored_rows"]), "labeled_censored_rows": censored_labeled},
            requirement="right-censored contracts never receive a negative/positive label",
        )
        add_validation(
            validation_records,
            check_id="labels_binary_or_null",
            category="target",
            passed=(
                invalid_eligible_labels == 0
                and noneligible_labeled == 0
                and positives + negatives == eligible
            ),
            observed={
                "eligible": eligible,
                "positives": positives,
                "negatives": negatives,
                "invalid_eligible_labels": invalid_eligible_labels,
                "noneligible_labeled": noneligible_labeled,
            },
            requirement="every eligible contract has a binary label and every non-eligible contract remains null",
        )
        positive_without_event = int(
            con.execute(
                f"SELECT COUNT(*) FROM {labels} WHERE {gold_spec.target.name}=1 AND first_qualifying_event_at IS NULL"
            ).fetchone()[0]
        )
        negative_with_event = int(
            con.execute(
                f"SELECT COUNT(*) FROM {labels} WHERE {gold_spec.target.name}=0 AND first_qualifying_event_at IS NOT NULL"
            ).fetchone()[0]
        )
        post_cutoff_positive_event = int(
            con.execute(
                f"SELECT COUNT(*) FROM {labels} WHERE {gold_spec.target.name}=1 AND first_qualifying_event_at > label_cutoff"
            ).fetchone()[0]
        )
        add_validation(
            validation_records,
            check_id="label_event_consistency",
            category="target",
            passed=positive_without_event == 0 and negative_with_event == 0,
            observed={"positive_without_event": positive_without_event, "negative_with_event": negative_with_event},
            requirement="positive/negative labels agree with qualifying-event evidence",
        )
        add_validation(
            validation_records,
            check_id="no_post_cutoff_positive_events",
            category="temporal",
            passed=post_cutoff_positive_event == 0,
            observed={"violations": post_cutoff_positive_event},
            requirement="no positive label is supported by an event after the demonstrated label cutoff",
        )
        add_validation(
            validation_records,
            check_id="target_population_sufficient",
            category="feasibility",
            passed=eligible >= target.min_eligible_rows and positives >= target.min_positive_rows,
            observed={"eligible": eligible, "positives": positives, "minimum_eligible": target.min_eligible_rows, "minimum_positives": target.min_positive_rows},
            requirement="eligible and positive populations are sufficient for downstream temporal modeling",
        )
        add_validation(
            validation_records,
            check_id="target_prevalence_sane",
            category="feasibility",
            passed=target.min_prevalence <= prevalence <= target.max_prevalence,
            observed={"prevalence": prevalence, "min": target.min_prevalence, "max": target.max_prevalence},
            requirement="target prevalence lies within configured sanity bounds",
        )
        add_validation(
            validation_records,
            check_id="label_cutoff_observed",
            category="temporal",
            passed=label_cutoff is not None,
            observed={"label_cutoff": str(label_cutoff), "strategy": target.label_cutoff_strategy},
            requirement="label cutoff is derived from observed canonical event coverage",
        )
        validation = pd.DataFrame.from_records(validation_records)

        write_report(validation, reports_root / "gold" / "20_target_validation.parquet")
        write_report(by_year, reports_root / "gold" / "20_target_by_year.parquet")
        write_report(event_scope, reports_root / "gold" / "20_target_event_scope.parquet")
        write_report(censoring, reports_root / "gold" / "20_target_censoring.parquet")
    finally:
        con.close()

    manifest_path = write_manifest(
        manifest_dir / "gold_target_y_addition_180d.json",
        {
            "milestone": "M3",
            "component": "20_target_engineering",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": gold_spec.schema_version,
            "target_name": gold_spec.target.name,
            "t0_column": gold_spec.target.t0_column,
            "horizon_days": gold_spec.target.horizon_days,
            "included_event_types": list(gold_spec.target.included_event_types),
            "label_cutoff_strategy": gold_spec.target.label_cutoff_strategy,
            "artifacts": {name: str(path) for name, path in artifacts.items()},
            "blocking_validation_passed": bool(
                validation.loc[validation["blocking"], "passed"].all()
            ),
        },
    )
    return TargetBuildResult(artifacts, validation, by_year, event_scope, censoring, manifest_path)
