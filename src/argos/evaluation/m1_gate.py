from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class GateDecision:
    status: str
    passed: int
    total: int
    failed_checks: tuple[str, ...]

    @property
    def closed(self) -> bool:
        return self.status == "CLOSED"


def _scalar(frame: pd.DataFrame, column: str, default: Any = None) -> Any:
    if frame.empty or column not in frame.columns:
        return default
    value = frame.iloc[0][column]
    if value is None:
        return default
    # ``pd.isna`` on list-like Parquet values returns an array, which cannot be
    # used as a boolean. Gate report cells can legitimately contain lists.
    if isinstance(value, (list, tuple, dict, set)):
        return value
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return value
    if not hasattr(missing, "__len__") and bool(missing):
        return default
    return value


def _check(
    records: list[dict[str, object]],
    *,
    check_id: str,
    category: str,
    description: str,
    passed: bool,
    observed: object,
    requirement: str,
    blocking: bool = True,
) -> None:
    records.append(
        {
            "check_id": check_id,
            "category": category,
            "description": description,
            "blocking": blocking,
            "passed": bool(passed),
            "observed": str(observed),
            "requirement": requirement,
        }
    )


def evaluate_m1_gate(
    reports_root: Path,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, GateDecision]:
    """Evaluate the M1 -> Silver gate from persisted profiling evidence.

    A check only closes when the required report exists and supports the
    criterion. Missing/stale evidence never silently passes.
    """
    profiling = reports_root / "profiling"
    quality = reports_root / "quality"
    gate_cfg = config["m1_gate"]
    deferred = set(config.get("m1_scope", {}).get("deferred_datasets", []))

    required_files = {
        "inventory": profiling / "dataset_inventory.parquet",
        "keys": profiling / "key_analysis.parquet",
        "grain": profiling / "grain_resolution.parquet",
        "joins": profiling / "join_analysis.parquet",
        "relationship_resolution": profiling / "relationship_resolution.parquet",
        "temporal": profiling / "temporal_profile.parquet",
        "target_horizons": profiling / "target_feasibility_horizons.parquet",
        "target_diagnostics": profiling / "target_feasibility_diagnostics.parquet",
        "addition_types": profiling / "addition_event_type_profile.parquet",
        "quality": quality / "quality_issue_register.parquet",
    }

    missing_files = [name for name, path in required_files.items() if not path.exists()]
    if missing_files:
        records: list[dict[str, object]] = []
        _check(
            records,
            check_id="evidence_complete",
            category="evidence",
            description="All M1 gate reports exist",
            passed=False,
            observed=f"missing={missing_files}",
            requirement="run notebooks 00-06 with the remediated code",
        )
        frame = pd.DataFrame.from_records(records)
        return frame, GateDecision("OPEN", 0, 1, ("evidence_complete",))

    inventory = pd.read_parquet(required_files["inventory"])
    keys = pd.read_parquet(required_files["keys"])
    grain = pd.read_parquet(required_files["grain"])
    joins = pd.read_parquet(required_files["joins"])
    relationship_resolution = pd.read_parquet(required_files["relationship_resolution"])
    temporal = pd.read_parquet(required_files["temporal"])
    horizons = pd.read_parquet(required_files["target_horizons"])
    diagnostics = pd.read_parquet(required_files["target_diagnostics"])
    addition_types = pd.read_parquet(required_files["addition_types"])
    quality_issues = pd.read_parquet(required_files["quality"])

    records: list[dict[str, object]] = []

    required_dataset_count = int(gate_cfg["required_dataset_count"])
    positive_inventory = inventory.loc[inventory["row_count"].fillna(0) > 0]
    _check(
        records,
        check_id="inventory_complete",
        category="inventory",
        description="All required Bronze datasets are inventoried with rows",
        passed=(
            inventory["dataset"].nunique() >= required_dataset_count
            and positive_inventory["dataset"].nunique() >= required_dataset_count
        ),
        observed=(
            f"datasets={inventory['dataset'].nunique()}, "
            f"nonempty={positive_inventory['dataset'].nunique()}"
        ),
        requirement=f">= {required_dataset_count} non-empty datasets",
    )

    has_ragged_metric = "ragged_row_count" in inventory.columns
    ragged_total = (
        int(inventory["ragged_row_count"].fillna(0).sum())
        if has_ragged_metric
        else -1
    )
    _check(
        records,
        check_id="bronze_structural_integrity",
        category="inventory",
        description="Bronze CSV records have the header-defined field count",
        passed=has_ragged_metric and ragged_total == 0,
        observed=(
            f"ragged_rows={ragged_total}"
            if has_ragged_metric
            else "ragged_row_count metric missing; rerun notebook 00"
        ),
        requirement="ragged_row_count = 0 across active snapshots",
    )

    def key_row(dataset: str, candidate: str) -> pd.DataFrame:
        return keys.loc[
            (keys["dataset"] == dataset)
            & (keys["candidate_key"] == candidate)
            & (keys["status"] == "analyzed")
        ]

    contracts_pk = key_row("contracts", "id_contrato")
    contracts_pk_ok = (
        not contracts_pk.empty
        and float(_scalar(contracts_pk, "null_key_rate", 1.0)) == 0.0
        and float(_scalar(contracts_pk, "uniqueness_ratio", 0.0)) == 1.0
    )
    _check(
        records,
        check_id="contracts_primary_key",
        category="grain",
        description="Contracts has a non-null unique technical key",
        passed=contracts_pk_ok,
        observed={
            "null_rate": _scalar(contracts_pk, "null_key_rate"),
            "uniqueness": _scalar(contracts_pk, "uniqueness_ratio"),
        },
        requirement="id_contrato null_rate=0 and uniqueness=1",
    )

    suppliers_pk = key_row("suppliers", "codigo")
    suppliers_pk_ok = (
        not suppliers_pk.empty
        and float(_scalar(suppliers_pk, "null_key_rate", 1.0)) == 0.0
        and float(_scalar(suppliers_pk, "uniqueness_ratio", 0.0)) == 1.0
    )
    _check(
        records,
        check_id="suppliers_primary_key",
        category="grain",
        description="Suppliers has a non-null unique technical key",
        passed=suppliers_pk_ok,
        observed={
            "null_rate": _scalar(suppliers_pk, "null_key_rate"),
            "uniqueness": _scalar(suppliers_pk, "uniqueness_ratio"),
        },
        requirement="codigo null_rate=0 and uniqueness=1",
    )

    # Process grain is evaluated against the identifier that notebook 03 actually
    # selected for contracts -> processes, not against a hard-coded assumption.
    resolved_cp_for_grain = relationship_resolution.loc[
        relationship_resolution["relationship"] == "contracts_processes"
    ]
    selected_right = _scalar(resolved_cp_for_grain, "selected_right_keys", [])
    if hasattr(selected_right, "tolist"):
        selected_right = selected_right.tolist()
    if isinstance(selected_right, str):
        selected_right = [selected_right]
    selected_process_key = "+".join(str(value) for value in selected_right)
    process_grain = grain.loc[
        (grain["dataset"] == "processes") & (grain["key"] == selected_process_key)
    ]
    _check(
        records,
        check_id="processes_grain_characterized",
        category="grain",
        description="The selected process join key is characterized before Silver canonicalization",
        passed=(
            bool(selected_process_key)
            and not process_grain.empty
            and _scalar(process_grain, "status") == "analyzed"
            and _scalar(process_grain, "grain_interpretation") is not None
        ),
        observed={
            "selected_key": selected_process_key,
            "interpretation": _scalar(process_grain, "grain_interpretation"),
            "duplicate_keys": _scalar(process_grain, "duplicate_key_count"),
            "conflicting_keys": _scalar(process_grain, "conflicting_duplicate_key_count"),
        },
        requirement="selected relationship key has a duplicate/payload diagnostic",
    )

    addition_grain = grain.loc[
        (grain["dataset"] == "additions")
        & (grain["key"] == "id_contrato+fecharegistro+tipo")
    ]
    _check(
        records,
        check_id="additions_grain_characterized",
        category="grain",
        description="Addition-event duplication is characterized",
        passed=(
            not addition_grain.empty
            and _scalar(addition_grain, "status") == "analyzed"
            and _scalar(addition_grain, "grain_interpretation") is not None
        ),
        observed={
            "interpretation": _scalar(addition_grain, "grain_interpretation"),
            "duplicate_excess": _scalar(addition_grain, "duplicate_excess_rows"),
        },
        requirement="event-key duplication diagnostic exists",
    )

    resolved_cp = relationship_resolution.loc[
        relationship_resolution["relationship"] == "contracts_processes"
    ]
    cp_min = float(gate_cfg["relationship_candidate_min_coverage"])
    cp_coverage = float(_scalar(resolved_cp, "left_row_coverage", 0.0))
    _check(
        records,
        check_id="contracts_processes_resolved",
        category="relationships",
        description="Contracts -> Processes uses an empirically resolved key",
        passed=(
            not resolved_cp.empty
            and _scalar(resolved_cp, "status") == "resolved"
            and cp_coverage >= cp_min
        ),
        observed={
            "right_keys": _scalar(resolved_cp, "selected_right_keys"),
            "coverage": cp_coverage,
            "requires_canonicalization": _scalar(
                resolved_cp, "requires_right_canonicalization"
            ),
        },
        requirement=f"coverage >= {cp_min:.2%}",
    )

    def relationship_check(name: str, minimum: float) -> tuple[bool, object]:
        row = joins.loc[(joins["relationship"] == name) & (joins["status"] == "analyzed")]
        coverage = float(_scalar(row, "left_row_coverage", 0.0))
        return (not row.empty and coverage >= minimum), {
            "coverage": coverage,
            "expansion": _scalar(row, "expansion_factor"),
            "right_multiplicity": _scalar(row, "max_right_multiplicity"),
        }

    for name, threshold_key, description in [
        (
            "contracts_suppliers",
            "contracts_suppliers_min_coverage",
            "Contracts -> Suppliers has sufficient identifier coverage",
        ),
        (
            "additions_contracts",
            "additions_contracts_min_coverage",
            "Additions -> Contracts has sufficient identifier coverage",
        ),
        (
            "bidders_processes",
            "bidders_processes_min_coverage",
            "Bidders -> Processes has sufficient identifier coverage",
        ),
        (
            "bidders_suppliers",
            "bidders_suppliers_min_coverage",
            "Bidders -> Suppliers uses Codigo Proveedor and has sufficient coverage",
        ),
    ]:
        minimum = float(gate_cfg[threshold_key])
        passed, observed = relationship_check(name, minimum)
        _check(
            records,
            check_id=f"relationship_{name}",
            category="relationships",
            description=description,
            passed=passed,
            observed=observed,
            requirement=f"coverage >= {minimum:.2%}",
        )

    t0_name = normalize_for_gate(config["target"]["candidate_t0_column"])
    t0 = temporal.loc[
        (temporal["dataset"] == config["target"]["candidate_t0_dataset"])
        & (temporal["normalized_column"] == t0_name)
    ]
    t0_coverage = float(_scalar(t0, "coverage", 0.0))
    t0_parse = float(_scalar(t0, "parse_success_rate_nonnull", 0.0))
    t0_plausible = float(_scalar(t0, "plausible_rate_parsed", 0.0))
    _check(
        records,
        check_id="t0_temporal_quality",
        category="temporal",
        description="Candidate t0 has sufficient coverage, parseability and plausibility",
        passed=(
            not t0.empty
            and t0_coverage >= float(gate_cfg["t0_min_raw_coverage"])
            and t0_parse >= float(gate_cfg["t0_min_parse_success_nonnull"])
            and t0_plausible >= float(gate_cfg["t0_min_plausible_rate_parsed"])
        ),
        observed={
            "coverage": t0_coverage,
            "parse_success": t0_parse,
            "plausible_rate": t0_plausible,
        },
        requirement=(
            f"coverage>={float(gate_cfg['t0_min_raw_coverage']):.2%}, "
            f"parse>={float(gate_cfg['t0_min_parse_success_nonnull']):.2%}, "
            f"plausible>={float(gate_cfg['t0_min_plausible_rate_parsed']):.2%}"
        ),
    )

    addition_event_name = normalize_for_gate(config["target"]["addition_event_column"])
    addition_event = temporal.loc[
        (temporal["dataset"] == "additions")
        & (temporal["normalized_column"] == addition_event_name)
    ]
    event_parse = float(_scalar(addition_event, "parse_success_rate_nonnull", 0.0))
    event_parse_min = float(gate_cfg["addition_event_min_parse_success_nonnull"])
    _check(
        records,
        check_id="addition_event_time_quality",
        category="temporal",
        description="Addition event timestamp is reliably parseable",
        passed=not addition_event.empty and event_parse >= event_parse_min,
        observed={"parse_success": event_parse},
        requirement=f"parse >= {event_parse_min:.2%}",
    )

    _check(
        records,
        check_id="addition_event_scope_profiled",
        category="target",
        description="Adiciones Tipo values are profiled before freezing event semantics",
        passed=(
            not addition_types.empty
            and int(addition_types.get("source_rows", pd.Series(dtype=int)).fillna(0).sum()) > 0
        ),
        observed={
            "event_types": int(len(addition_types)),
            "source_rows": int(
                addition_types.get("source_rows", pd.Series(dtype=int)).fillna(0).sum()
            ),
        },
        requirement="non-empty event-type profile persisted by notebook 06",
    )

    diag = diagnostics.iloc[[0]] if not diagnostics.empty else diagnostics
    diag_t0_parse = float(_scalar(diag, "t0_parse_success_rate_nonnull_contracts", 0.0))
    diag_event_parse = float(_scalar(diag, "addition_event_parse_success_rate_nonnull", 0.0))
    dedup_key = _scalar(diag, "event_deduplication_key")
    _check(
        records,
        check_id="target_diagnostics_temporally_valid",
        category="target",
        description="Target builder uses parsed t0 and deduplicated parsed events",
        passed=(
            not diag.empty
            and diag_t0_parse >= float(gate_cfg["t0_min_parse_success_nonnull"])
            and diag_event_parse >= event_parse_min
            and bool(dedup_key)
        ),
        observed={
            "t0_parse": diag_t0_parse,
            "event_parse": diag_event_parse,
            "dedup_key": dedup_key,
            "duplicate_event_rate": _scalar(diag, "addition_event_duplicate_rate"),
        },
        requirement="target diagnostics clear parser thresholds and use explicit event deduplication",
    )

    horizon_days = int(config["target"]["horizon_days"])
    target_row = horizons.loc[horizons["horizon_days"] == horizon_days]
    eligible = int(_scalar(target_row, "eligible", 0))
    positives = int(_scalar(target_row, "positives", 0))
    negatives = int(_scalar(target_row, "negatives", 0))
    prevalence = float(_scalar(target_row, "prevalence", -1.0))
    target_ok = (
        not target_row.empty
        and eligible >= int(gate_cfg["target_min_eligible"])
        and positives >= int(gate_cfg["target_min_positives"])
        and positives + negatives == eligible
        and float(gate_cfg["target_prevalence_min"])
        <= prevalence
        <= float(gate_cfg["target_prevalence_max"])
    )
    _check(
        records,
        check_id="target_180d_feasible",
        category="target",
        description=f"y_addition_{horizon_days}d has observable positives and negatives",
        passed=target_ok,
        observed={
            "eligible": eligible,
            "positives": positives,
            "negatives": negatives,
            "prevalence": prevalence,
        },
        requirement=(
            f"eligible>={int(gate_cfg['target_min_eligible'])}, "
            f"positives>={int(gate_cfg['target_min_positives'])}, "
            "positives+negatives=eligible, prevalence within configured sanity bounds"
        ),
    )

    leakage_count = int(
        (
            quality_issues.get("rule", pd.Series(dtype=str))
            == "potential_temporal_leakage"
        ).sum()
    )
    _check(
        records,
        check_id="leakage_register_present",
        category="quality",
        description="Known post-t0/mutable fields are explicitly registered as leakage risks",
        passed=leakage_count > 0,
        observed=f"potential_temporal_leakage={leakage_count}",
        requirement="> 0 documented leakage-risk fields",
    )

    _check(
        records,
        check_id="deferred_sources_explicit",
        category="scope",
        description="Non-blocking V1 sources are explicitly deferred rather than silently ignored",
        passed={"payments", "sanctions"}.issubset(deferred),
        observed=sorted(deferred),
        requirement="payments and sanctions explicitly listed as deferred for addition-risk V1",
    )

    report = pd.DataFrame.from_records(records)
    blocking = report.loc[report["blocking"]]
    failed = tuple(blocking.loc[~blocking["passed"], "check_id"].tolist())
    passed_count = int(blocking["passed"].sum())
    total = int(len(blocking))
    status = "CLOSED" if not failed else "OPEN"
    return report, GateDecision(status, passed_count, total, failed)


def normalize_for_gate(value: str) -> str:
    """Small local normalizer to keep gate evaluation independent of source schemas."""
    from argos.common.names import normalize_name

    return normalize_name(value)


def render_m1_gate_markdown(report: pd.DataFrame, decision: GateDecision) -> str:
    """Render the auditable M1 gate decision as Markdown."""
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status_label = "M1 ✅ CLOSED" if decision.closed else "M1 ❌ OPEN"
    lines = [
        "# ARGOS — M1 Data Understanding Gate",
        "",
        f"**Status:** {status_label}",
        "",
        f"Generated: `{generated}`",
        "",
        f"Blocking checks passed: **{decision.passed}/{decision.total}**.",
        "",
        "| Check | Category | Result | Observed | Requirement |",
        "|---|---|---|---|---|",
    ]

    for row in report.itertuples(index=False):
        result = "PASS" if row.passed else "FAIL"
        observed = str(row.observed).replace("|", "\\|").replace("\n", " ")
        requirement = str(row.requirement).replace("|", "\\|").replace("\n", " ")
        description = str(row.description).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{row.check_id}` — {description} | {row.category} | {result} | "
            f"{observed} | {requirement} |"
        )

    lines.extend(
        [
            "",
            "## Decision",
            "",
        ]
    )
    if decision.closed:
        lines.extend(
            [
                "M1 is closed for the **addition-risk V1 scope**. The project may proceed "
                "to Silver. Payments and sanctions remain explicitly deferred and do not "
                "become modeling inputs until their own data-quality gates are resolved.",
                "",
                "The closure does not authorize mutable/post-t0 fields as model features. "
                "Point-in-time correctness remains mandatory in Gold feature engineering.",
            ]
        )
    else:
        lines.extend(
            [
                "M1 remains open. Blocking checks:",
                "",
                *[f"- `{check}`" for check in decision.failed_checks],
            ]
        )

    return "\n".join(lines) + "\n"
