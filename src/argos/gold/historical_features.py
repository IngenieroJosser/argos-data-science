from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import quote_identifier, sql_string
from argos.config.gold import GoldSpec
from argos.gold.utils import (
    add_validation,
    copy_query,
    parquet_source,
    require_columns,
    sql_list,
    write_manifest,
)


BUILD_IMPLEMENTATION = "m3-24-historical-features-out-of-core-v2"


@dataclass(frozen=True, slots=True)
class HistoricalFeaturesResult:
    artifact: Path
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def build_historical_features(
    *,
    silver_dir: Path,
    gold_dir: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> HistoricalFeaturesResult:
    contracts_path = silver_dir / "contracts.parquet"
    events_path = silver_dir / "addition_events.parquet"
    population_path = gold_dir / "target_population.parquet"
    for path in [contracts_path, events_path, population_path]:
        if not path.exists():
            raise FileNotFoundError(f"Notebook 24 requires {path}")

    artifact = gold_dir / "features" / "historical_features.parquet"
    contracts = parquet_source(contracts_path)
    events = parquet_source(events_path)
    population = parquet_source(population_path)
    work_dir = (temp_directory or gold_dir / ".duckdb_tmp") / "m3_24"
    work_dir.mkdir(parents=True, exist_ok=True)
    base_path = work_dir / "base.parquet"
    contract_history_path = work_dir / "contract_history.parquet"
    qualifying_events_path = work_dir / "qualifying_events.parquet"
    supplier_event_cum_path = work_dir / "supplier_event_cum.parquet"
    supplier_contract_event_cum_path = work_dir / "supplier_contract_event_cum.parquet"
    entity_event_cum_path = work_dir / "entity_event_cum.parquet"
    pair_event_cum_path = work_dir / "pair_event_cum.parquet"

    con = connect(
        temp_directory=temp_directory,
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    entity_key = gold_spec.historical_features.entity_key
    supplier_key = gold_spec.historical_features.supplier_key
    included = sql_list(gold_spec.historical_features.qualifying_event_types)
    try:
        require_columns(
            con,
            contracts,
            ["contract_id", supplier_key, entity_key],
            label="contracts.parquet",
        )
        require_columns(
            con,
            population,
            ["contract_id", "t0"],
            label="target_population.parquet",
        )
        require_columns(
            con,
            events,
            ["contract_id", "event_at", "event_type"],
            label="addition_events.parquet",
        )

        entity_q = quote_identifier(entity_key)
        supplier_q = quote_identifier(supplier_key)

        print("[24] staging contract identities and valid t0 rows...")
        base_query = f"""
            SELECT
                p.contract_id,
                p.t0,
                c.{supplier_q} AS supplier_code,
                c.{entity_q} AS entity_id
            FROM {population} p
            JOIN {contracts} c USING (contract_id)
            WHERE p.t0 IS NOT NULL
        """
        copy_query(
            con,
            base_query,
            base_path,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=True,
        )
        base = parquet_source(base_path)

        print("[24] computing prior contract history with same-t0 isolation...")
        contract_history_query = f"""
            WITH supplier_group AS (
                SELECT supplier_code, t0, COUNT(*)::BIGINT AS contracts_at_t0
                FROM {base}
                WHERE supplier_code IS NOT NULL
                GROUP BY supplier_code, t0
            ), supplier_hist AS (
                SELECT
                    supplier_code,
                    t0,
                    COALESCE(SUM(contracts_at_t0) OVER (
                        PARTITION BY supplier_code ORDER BY t0
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0)::BIGINT AS prior_supplier_contract_count,
                    MIN(t0) OVER (
                        PARTITION BY supplier_code ORDER BY t0
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ) AS first_prior_supplier_contract_at,
                    MAX(t0) OVER (
                        PARTITION BY supplier_code ORDER BY t0
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ) AS last_prior_supplier_contract_at
                FROM supplier_group
            ), entity_group AS (
                SELECT entity_id, t0, COUNT(*)::BIGINT AS contracts_at_t0
                FROM {base}
                WHERE entity_id IS NOT NULL
                GROUP BY entity_id, t0
            ), entity_hist AS (
                SELECT
                    entity_id,
                    t0,
                    COALESCE(SUM(contracts_at_t0) OVER (
                        PARTITION BY entity_id ORDER BY t0
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0)::BIGINT AS prior_entity_contract_count,
                    MIN(t0) OVER (
                        PARTITION BY entity_id ORDER BY t0
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ) AS first_prior_entity_contract_at,
                    MAX(t0) OVER (
                        PARTITION BY entity_id ORDER BY t0
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ) AS last_prior_entity_contract_at
                FROM entity_group
            ), pair_group AS (
                SELECT supplier_code, entity_id, t0, COUNT(*)::BIGINT AS contracts_at_t0
                FROM {base}
                WHERE supplier_code IS NOT NULL AND entity_id IS NOT NULL
                GROUP BY supplier_code, entity_id, t0
            ), pair_hist AS (
                SELECT
                    supplier_code,
                    entity_id,
                    t0,
                    COALESCE(SUM(contracts_at_t0) OVER (
                        PARTITION BY supplier_code, entity_id ORDER BY t0
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0)::BIGINT AS prior_supplier_entity_contract_count,
                    MAX(t0) OVER (
                        PARTITION BY supplier_code, entity_id ORDER BY t0
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ) AS last_prior_supplier_entity_contract_at
                FROM pair_group
            )
            SELECT
                b.*,
                COALESCE(sh.prior_supplier_contract_count, 0)::BIGINT AS prior_supplier_contract_count,
                sh.first_prior_supplier_contract_at,
                sh.last_prior_supplier_contract_at,
                COALESCE(eh.prior_entity_contract_count, 0)::BIGINT AS prior_entity_contract_count,
                eh.first_prior_entity_contract_at,
                eh.last_prior_entity_contract_at,
                COALESCE(ph.prior_supplier_entity_contract_count, 0)::BIGINT AS prior_supplier_entity_contract_count,
                ph.last_prior_supplier_entity_contract_at
            FROM {base} b
            LEFT JOIN supplier_hist sh
              ON b.supplier_code = sh.supplier_code AND b.t0 = sh.t0
            LEFT JOIN entity_hist eh
              ON b.entity_id = eh.entity_id AND b.t0 = eh.t0
            LEFT JOIN pair_hist ph
              ON b.supplier_code = ph.supplier_code
             AND b.entity_id = ph.entity_id
             AND b.t0 = ph.t0
        """
        copy_query(
            con,
            contract_history_query,
            contract_history_path,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=True,
        )

        print("[24] staging qualifying historical events...")
        qualifying_events_query = f"""
            SELECT
                e.contract_id,
                e.event_at,
                c.{supplier_q} AS supplier_code,
                c.{entity_q} AS entity_id
            FROM {events} e
            JOIN {contracts} c USING (contract_id)
            WHERE e.event_at IS NOT NULL
              AND UPPER(TRIM(e.event_type)) IN ({included})
        """
        copy_query(
            con,
            qualifying_events_query,
            qualifying_events_path,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=True,
        )
        qevents = parquet_source(qualifying_events_path)

        print("[24] building compact cumulative event histories...")
        copy_query(
            con,
            f"""
            WITH points AS (
                SELECT supplier_code, event_at, COUNT(*)::BIGINT AS events_at_time
                FROM {qevents}
                WHERE supplier_code IS NOT NULL
                GROUP BY supplier_code, event_at
            )
            SELECT supplier_code, event_at,
                   SUM(events_at_time) OVER (
                       PARTITION BY supplier_code ORDER BY event_at
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   )::BIGINT AS cumulative_supplier_addition_events
            FROM points
            """,
            supplier_event_cum_path,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=True,
        )
        copy_query(
            con,
            f"""
            WITH first_event AS (
                SELECT contract_id, MIN(event_at) AS first_event_at,
                       MIN(supplier_code) AS supplier_code
                FROM {qevents}
                GROUP BY contract_id
            ), points AS (
                SELECT supplier_code, first_event_at AS event_at,
                       COUNT(*)::BIGINT AS contracts_at_time
                FROM first_event
                WHERE supplier_code IS NOT NULL
                GROUP BY supplier_code, first_event_at
            )
            SELECT supplier_code, event_at,
                   SUM(contracts_at_time) OVER (
                       PARTITION BY supplier_code ORDER BY event_at
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   )::BIGINT AS cumulative_supplier_contracts_with_addition
            FROM points
            """,
            supplier_contract_event_cum_path,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=True,
        )
        copy_query(
            con,
            f"""
            WITH points AS (
                SELECT entity_id, event_at, COUNT(*)::BIGINT AS events_at_time
                FROM {qevents}
                WHERE entity_id IS NOT NULL
                GROUP BY entity_id, event_at
            )
            SELECT entity_id, event_at,
                   SUM(events_at_time) OVER (
                       PARTITION BY entity_id ORDER BY event_at
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   )::BIGINT AS cumulative_entity_addition_events
            FROM points
            """,
            entity_event_cum_path,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=True,
        )
        copy_query(
            con,
            f"""
            WITH points AS (
                SELECT supplier_code, entity_id, event_at,
                       COUNT(*)::BIGINT AS events_at_time
                FROM {qevents}
                WHERE supplier_code IS NOT NULL AND entity_id IS NOT NULL
                GROUP BY supplier_code, entity_id, event_at
            )
            SELECT supplier_code, entity_id, event_at,
                   SUM(events_at_time) OVER (
                       PARTITION BY supplier_code, entity_id ORDER BY event_at
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   )::BIGINT AS cumulative_supplier_entity_addition_events
            FROM points
            """,
            pair_event_cum_path,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=True,
        )

        history = parquet_source(contract_history_path)
        supplier_events = parquet_source(supplier_event_cum_path)
        supplier_contract_events = parquet_source(supplier_contract_event_cum_path)
        entity_events = parquet_source(entity_event_cum_path)
        pair_events = parquet_source(pair_event_cum_path)

        print("[24] as-of joining cumulative histories to each contract t0...")
        final_query = f"""
            WITH supplier_join AS (
                SELECT h.*, se.event_at AS max_supplier_addition_event_at,
                       COALESCE(se.cumulative_supplier_addition_events, 0)::BIGINT AS prior_supplier_addition_event_count
                FROM {history} h
                ASOF LEFT JOIN {supplier_events} se
                  ON h.supplier_code = se.supplier_code AND h.t0 > se.event_at
            ), supplier_contract_join AS (
                SELECT h.*, sc.event_at AS max_supplier_contract_addition_at,
                       COALESCE(sc.cumulative_supplier_contracts_with_addition, 0)::BIGINT AS prior_supplier_contracts_with_addition
                FROM supplier_join h
                ASOF LEFT JOIN {supplier_contract_events} sc
                  ON h.supplier_code = sc.supplier_code AND h.t0 > sc.event_at
            ), entity_join AS (
                SELECT h.*, ee.event_at AS max_entity_addition_event_at,
                       COALESCE(ee.cumulative_entity_addition_events, 0)::BIGINT AS prior_entity_addition_event_count
                FROM supplier_contract_join h
                ASOF LEFT JOIN {entity_events} ee
                  ON h.entity_id = ee.entity_id AND h.t0 > ee.event_at
            ), pair_join AS (
                SELECT h.*, pe.event_at AS max_supplier_entity_addition_event_at,
                       COALESCE(pe.cumulative_supplier_entity_addition_events, 0)::BIGINT AS prior_supplier_entity_addition_event_count
                FROM entity_join h
                ASOF LEFT JOIN {pair_events} pe
                  ON h.supplier_code = pe.supplier_code
                 AND h.entity_id = pe.entity_id
                 AND h.t0 > pe.event_at
            )
            SELECT
                contract_id,
                t0,
                prior_supplier_contract_count,
                prior_entity_contract_count,
                prior_supplier_entity_contract_count,
                CASE WHEN first_prior_supplier_contract_at IS NULL THEN NULL
                     ELSE DATE_DIFF('day', first_prior_supplier_contract_at, t0) END::INTEGER AS supplier_tenure_days,
                CASE WHEN last_prior_supplier_contract_at IS NULL THEN NULL
                     ELSE DATE_DIFF('day', last_prior_supplier_contract_at, t0) END::INTEGER AS days_since_supplier_last_contract,
                CASE WHEN first_prior_entity_contract_at IS NULL THEN NULL
                     ELSE DATE_DIFF('day', first_prior_entity_contract_at, t0) END::INTEGER AS entity_tenure_days,
                CASE WHEN last_prior_entity_contract_at IS NULL THEN NULL
                     ELSE DATE_DIFF('day', last_prior_entity_contract_at, t0) END::INTEGER AS days_since_entity_last_contract,
                prior_supplier_addition_event_count,
                prior_supplier_contracts_with_addition,
                prior_entity_addition_event_count,
                prior_supplier_entity_addition_event_count,
                CASE WHEN prior_supplier_contract_count = 0 THEN NULL
                     ELSE prior_supplier_contracts_with_addition::DOUBLE /
                          prior_supplier_contract_count END AS observed_supplier_addition_contract_share_before_t0,
                last_prior_supplier_contract_at AS _pit_max_supplier_contract_t0,
                last_prior_entity_contract_at AS _pit_max_entity_contract_t0,
                last_prior_supplier_entity_contract_at AS _pit_max_supplier_entity_contract_t0,
                max_supplier_addition_event_at AS _pit_max_supplier_addition_event_at,
                max_supplier_contract_addition_at AS _pit_max_supplier_contract_addition_at,
                max_entity_addition_event_at AS _pit_max_entity_addition_event_at,
                max_supplier_entity_addition_event_at AS _pit_max_supplier_entity_addition_event_at,
                {sql_string(gold_spec.schema_version)} AS _gold_schema_version
            FROM pair_join
        """
        copy_query(
            con,
            final_query,
            artifact,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=overwrite,
        )

        features = parquet_source(artifact)
        stats = con.execute(
            f"SELECT COUNT(*) AS row_count, COUNT(DISTINCT contract_id) AS distinct_contracts FROM {features}"
        ).fetchdf().iloc[0]
        expected = int(
            con.execute(f"SELECT COUNT(*) FROM {population} WHERE t0 IS NOT NULL").fetchone()[0]
        )
        future_violations = int(
            con.execute(
                f"""
                SELECT COUNT(*) FROM {features}
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
        negative_counts = int(
            con.execute(
                f"""
                SELECT COUNT(*) FROM {features}
                WHERE prior_supplier_contract_count < 0
                   OR prior_entity_contract_count < 0
                   OR prior_supplier_entity_contract_count < 0
                   OR prior_supplier_addition_event_count < 0
                   OR prior_entity_addition_event_count < 0
                """
            ).fetchone()[0]
        )

        records: list[dict[str, Any]] = []
        add_validation(
            records,
            check_id="historical_feature_grain",
            category="grain",
            passed=(
                int(stats["row_count"]) == expected
                and int(stats["distinct_contracts"]) == expected
            ),
            observed={
                "rows": int(stats["row_count"]),
                "distinct_contracts": int(stats["distinct_contracts"]),
                "expected": expected,
            },
            requirement="one historical-feature row per contract with valid t0",
        )
        add_validation(
            records,
            check_id="historical_features_strictly_before_t0",
            category="point_in_time",
            passed=(
                future_violations
                <= gold_spec.validation.max_feature_future_violations
            ),
            observed={"future_or_same_time_violations": future_violations},
            requirement="all historical source timestamps used by features are strictly < t0",
        )
        add_validation(
            records,
            check_id="historical_counts_nonnegative",
            category="features",
            passed=negative_counts == 0,
            observed={"violations": negative_counts},
            requirement="historical count features are non-negative",
        )
        validation = pd.DataFrame.from_records(records)
        write_report(
            validation,
            reports_root / "gold" / "24_historical_features_validation.parquet",
        )
    finally:
        con.close()
        shutil.rmtree(work_dir, ignore_errors=True)

    manifest_path = write_manifest(
        manifest_dir / "gold_historical_features.json",
        {
            "milestone": "M3",
            "component": "24_historical_features",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": gold_spec.schema_version,
            "artifact": str(artifact),
            "event_scope": list(
                gold_spec.historical_features.qualifying_event_types
            ),
            "pit_rule": "all history timestamps strictly < current contract t0",
            "blocking_validation_passed": bool(
                validation.loc[validation["blocking"], "passed"].all()
            ),
        },
    )
    return HistoricalFeaturesResult(artifact, validation, manifest_path)
