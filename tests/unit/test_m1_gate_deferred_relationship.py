from pathlib import Path

import pandas as pd

from argos.evaluation.m1_gate import evaluate_m1_gate


def test_measured_deferred_bidder_supplier_link_does_not_block_m1(
    tmp_path: Path, monkeypatch
) -> None:
    profiling = tmp_path / "profiling"
    quality = tmp_path / "quality"
    profiling.mkdir()
    quality.mkdir()

    names = {
        "dataset_inventory.parquet",
        "key_analysis.parquet",
        "grain_resolution.parquet",
        "join_analysis.parquet",
        "relationship_resolution.parquet",
        "temporal_profile.parquet",
        "target_feasibility_horizons.parquet",
        "target_feasibility_diagnostics.parquet",
        "addition_event_type_profile.parquet",
    }
    for name in names:
        (profiling / name).touch()
    (quality / "quality_issue_register.parquet").touch()

    frames = {
        "dataset_inventory.parquet": pd.DataFrame(
            {
                "dataset": [
                    "processes", "contracts", "bidders", "suppliers",
                    "additions", "sanctions", "payments",
                ],
                "row_count": [1] * 7,
                "ragged_row_count": [0] * 7,
            }
        ),
        "key_analysis.parquet": pd.DataFrame(
            [
                {
                    "dataset": "contracts", "candidate_key": "id_contrato",
                    "status": "analyzed", "null_key_rate": 0.0,
                    "uniqueness_ratio": 1.0,
                },
                {
                    "dataset": "suppliers", "candidate_key": "codigo",
                    "status": "analyzed", "null_key_rate": 0.0,
                    "uniqueness_ratio": 1.0,
                },
            ]
        ),
        "grain_resolution.parquet": pd.DataFrame(
            [
                {
                    "dataset": "processes", "key": "id_del_portafolio",
                    "status": "analyzed",
                    "grain_interpretation": "multiple_payload_variants_per_key",
                    "duplicate_key_count": 10,
                    "conflicting_duplicate_key_count": 3,
                    "duplicate_excess_rows": 10,
                },
                {
                    "dataset": "additions", "key": "id_contrato+fecharegistro+tipo",
                    "status": "analyzed",
                    "grain_interpretation": "multiple_payload_variants_per_key",
                    "duplicate_key_count": 10,
                    "conflicting_duplicate_key_count": 3,
                    "duplicate_excess_rows": 10,
                },
            ]
        ),
        "join_analysis.parquet": pd.DataFrame(
            [
                {"relationship": "contracts_suppliers", "status": "analyzed", "left_row_coverage": 0.95, "expansion_factor": 1.0, "max_right_multiplicity": 1},
                {"relationship": "additions_contracts", "status": "analyzed", "left_row_coverage": 1.0, "expansion_factor": 1.0, "max_right_multiplicity": 1},
                {"relationship": "bidders_processes", "status": "analyzed", "left_row_coverage": 0.99, "expansion_factor": 4.0, "max_right_multiplicity": 10},
                {"relationship": "bidders_suppliers", "status": "analyzed", "left_row_coverage": 0.0, "expansion_factor": 1.0, "max_right_multiplicity": 0},
            ]
        ),
        "relationship_resolution.parquet": pd.DataFrame(
            [
                {
                    "relationship": "contracts_processes", "status": "resolved",
                    "selected_right_keys": ["id_del_portafolio"],
                    "left_row_coverage": 0.97,
                    "requires_right_canonicalization": True,
                }
            ]
        ),
        "temporal_profile.parquet": pd.DataFrame(
            [
                {"dataset": "contracts", "normalized_column": "fecha_de_firma", "coverage": 0.93, "parse_success_rate_nonnull": 1.0, "plausible_rate_parsed": 1.0},
                {"dataset": "additions", "normalized_column": "fecharegistro", "coverage": 1.0, "parse_success_rate_nonnull": 1.0, "plausible_rate_parsed": 1.0},
            ]
        ),
        "target_feasibility_horizons.parquet": pd.DataFrame(
            [{"horizon_days": 180, "eligible": 100000, "positives": 1000, "negatives": 99000, "prevalence": 0.01}]
        ),
        "target_feasibility_diagnostics.parquet": pd.DataFrame(
            [{
                "t0_parse_success_rate_nonnull_contracts": 1.0,
                "addition_event_parse_success_rate_nonnull": 1.0,
                "event_deduplication_key": "contract_id+event_at+event_type",
                "addition_event_duplicate_rate": 0.5,
            }]
        ),
        "addition_event_type_profile.parquet": pd.DataFrame(
            [{"event_type": "MODIFICACION GENERAL", "source_rows": 1}]
        ),
        "quality_issue_register.parquet": pd.DataFrame(
            [{"rule": "potential_temporal_leakage"}]
        ),
    }

    def fake_read_parquet(path: Path, *args, **kwargs):
        return frames[Path(path).name].copy()

    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)

    config = {
        "target": {
            "horizon_days": 180,
            "candidate_t0_dataset": "contracts",
            "candidate_t0_column": "fecha_de_firma",
            "addition_event_column": "fecharegistro",
        },
        "m1_gate": {
            "required_dataset_count": 7,
            "relationship_candidate_min_coverage": 0.90,
            "contracts_suppliers_min_coverage": 0.90,
            "additions_contracts_min_coverage": 0.99,
            "bidders_processes_min_coverage": 0.95,
            "bidders_suppliers_min_coverage": 0.90,
            "t0_min_raw_coverage": 0.85,
            "t0_min_parse_success_nonnull": 0.98,
            "t0_min_plausible_rate_parsed": 0.995,
            "addition_event_min_parse_success_nonnull": 0.99,
            "target_min_eligible": 100000,
            "target_min_positives": 1000,
            "target_prevalence_min": 0.005,
            "target_prevalence_max": 0.80,
        },
        "m1_scope": {
            "deferred_datasets": ["payments", "sanctions"],
            "deferred_relationships": ["bidders_suppliers"],
        },
    }

    report, decision = evaluate_m1_gate(tmp_path, config)

    assert decision.closed is True
    bidder_check = report.loc[
        report["check_id"] == "relationship_bidders_suppliers"
    ].iloc[0]
    assert bool(bidder_check["passed"]) is False
    assert bool(bidder_check["blocking"]) is False
    deferred_check = report.loc[
        report["check_id"] == "bidders_suppliers_resolution_deferred"
    ].iloc[0]
    assert bool(deferred_check["passed"]) is True
    assert bool(deferred_check["blocking"]) is True
