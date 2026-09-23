from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class M7CoreSpec:
    schema_version: str
    model_version: str
    benchmark_gold_schema: str
    benchmark_model_schema: str
    benchmark_robustness_schema: str
    benchmark_production_schema: str
    protocol_freeze_date: date
    prospective_start: date
    target_horizon_days: int
    operating_mode: str


@dataclass(frozen=True, slots=True)
class CohortSpec:
    frequency: str
    min_scoring_batches: int
    min_shadow_days: int
    min_matured_cohorts: int
    min_matured_rows: int
    min_matured_positives: int
    observation_end_source: str
    outcome_reporting_lag_days: int


@dataclass(frozen=True, slots=True)
class OutcomeSpec:
    target_column: str
    id_column: str
    t0_column: str
    event_type: str
    event_time_column: str
    window_open: str
    window_close: str
    require_full_followup: bool
    label_lock_root: str


@dataclass(frozen=True, slots=True)
class PerformanceSpec:
    operational_fraction: float
    min_pr_auc_over_prevalence: float
    min_lift_at_operational_k: float
    max_ece: float
    max_brier_relative_to_prevalence_baseline: float
    bootstrap_replicates: int
    confidence_level: float


@dataclass(frozen=True, slots=True)
class OperationsSpec:
    review_queue_root: str
    scored_batch_root: str
    min_review_completion_rate: float
    max_p95_review_latency_hours: float
    require_audit_chain: bool
    require_zero_critical_incidents_for_pilot: bool
    terminal_review_statuses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MonitoringSpec:
    score_psi_warning: float
    score_psi_high: float
    feature_psi_warning: float
    feature_psi_high: float
    max_high_alert_fraction: float


@dataclass(frozen=True, slots=True)
class GovernanceSpec:
    consumed_test_year: int
    consumed_oot_year: int
    allow_reuse_consumed_holdouts_for_selection: bool
    human_review_required: bool
    automatic_production_promotion: bool
    allowed_decisions: tuple[str, ...]
    new_model_requires_new_future_holdout: bool


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    protocol_manifest: str
    cohort_registry: str
    label_lock_registry: str
    decision_record: str
    incident_register: str


@dataclass(frozen=True, slots=True)
class AcceptanceSpec:
    require_m6_closed: bool
    require_frozen_protocol_hashes: bool
    require_future_only_cohorts: bool
    require_matured_outcome_evaluation: bool
    require_human_review_evidence: bool
    require_longitudinal_monitoring: bool
    require_explicit_decision_record: bool


@dataclass(frozen=True, slots=True)
class ProspectiveSpec:
    core: M7CoreSpec
    cohorts: CohortSpec
    outcomes: OutcomeSpec
    performance: PerformanceSpec
    operations: OperationsSpec
    monitoring: MonitoringSpec
    governance: GovernanceSpec
    artifacts: ArtifactSpec
    acceptance: AcceptanceSpec

    @property
    def schema_version(self) -> str:
        return self.core.schema_version


def load_prospective_spec(path: Path) -> ProspectiveSpec:
    with Path(path).open("rb") as fh:
        raw = tomllib.load(fh)

    m7 = raw["m7"]
    c = raw["cohorts"]
    o = raw["outcomes"]
    p = raw["performance"]
    ops = raw["operations"]
    mon = raw["monitoring"]
    gov = raw["governance"]
    art = raw["artifacts"]
    acc = raw["acceptance"]

    spec = ProspectiveSpec(
        core=M7CoreSpec(
            schema_version=str(m7["schema_version"]),
            model_version=str(m7["model_version"]),
            benchmark_gold_schema=str(m7["benchmark_gold_schema"]),
            benchmark_model_schema=str(m7["benchmark_model_schema"]),
            benchmark_robustness_schema=str(m7["benchmark_robustness_schema"]),
            benchmark_production_schema=str(m7["benchmark_production_schema"]),
            protocol_freeze_date=date.fromisoformat(str(m7["protocol_freeze_date"])),
            prospective_start=date.fromisoformat(str(m7["prospective_start"])),
            target_horizon_days=int(m7["target_horizon_days"]),
            operating_mode=str(m7["operating_mode"]),
        ),
        cohorts=CohortSpec(
            frequency=str(c["frequency"]),
            min_scoring_batches=int(c["min_scoring_batches"]),
            min_shadow_days=int(c["min_shadow_days"]),
            min_matured_cohorts=int(c["min_matured_cohorts"]),
            min_matured_rows=int(c["min_matured_rows"]),
            min_matured_positives=int(c["min_matured_positives"]),
            observation_end_source=str(c["observation_end_source"]),
            outcome_reporting_lag_days=int(c["outcome_reporting_lag_days"]),
        ),
        outcomes=OutcomeSpec(
            target_column=str(o["target_column"]),
            id_column=str(o["id_column"]),
            t0_column=str(o["t0_column"]),
            event_type=str(o["event_type"]),
            event_time_column=str(o["event_time_column"]),
            window_open=str(o["window_open"]),
            window_close=str(o["window_close"]),
            require_full_followup=bool(o["require_full_followup"]),
            label_lock_root=str(o["label_lock_root"]),
        ),
        performance=PerformanceSpec(
            operational_fraction=float(p["operational_fraction"]),
            min_pr_auc_over_prevalence=float(p["min_pr_auc_over_prevalence"]),
            min_lift_at_operational_k=float(p["min_lift_at_operational_k"]),
            max_ece=float(p["max_ece"]),
            max_brier_relative_to_prevalence_baseline=float(
                p["max_brier_relative_to_prevalence_baseline"]
            ),
            bootstrap_replicates=int(p["bootstrap_replicates"]),
            confidence_level=float(p["confidence_level"]),
        ),
        operations=OperationsSpec(
            review_queue_root=str(ops["review_queue_root"]),
            scored_batch_root=str(ops["scored_batch_root"]),
            min_review_completion_rate=float(ops["min_review_completion_rate"]),
            max_p95_review_latency_hours=float(ops["max_p95_review_latency_hours"]),
            require_audit_chain=bool(ops["require_audit_chain"]),
            require_zero_critical_incidents_for_pilot=bool(
                ops["require_zero_critical_incidents_for_pilot"]
            ),
            terminal_review_statuses=tuple(str(v).lower() for v in ops["terminal_review_statuses"]),
        ),
        monitoring=MonitoringSpec(
            score_psi_warning=float(mon["score_psi_warning"]),
            score_psi_high=float(mon["score_psi_high"]),
            feature_psi_warning=float(mon["feature_psi_warning"]),
            feature_psi_high=float(mon["feature_psi_high"]),
            max_high_alert_fraction=float(mon["max_high_alert_fraction"]),
        ),
        governance=GovernanceSpec(
            consumed_test_year=int(gov["consumed_test_year"]),
            consumed_oot_year=int(gov["consumed_oot_year"]),
            allow_reuse_consumed_holdouts_for_selection=bool(
                gov["allow_reuse_consumed_holdouts_for_selection"]
            ),
            human_review_required=bool(gov["human_review_required"]),
            automatic_production_promotion=bool(gov["automatic_production_promotion"]),
            allowed_decisions=tuple(str(v) for v in gov["allowed_decisions"]),
            new_model_requires_new_future_holdout=bool(
                gov["new_model_requires_new_future_holdout"]
            ),
        ),
        artifacts=ArtifactSpec(
            protocol_manifest=str(art["protocol_manifest"]),
            cohort_registry=str(art["cohort_registry"]),
            label_lock_registry=str(art["label_lock_registry"]),
            decision_record=str(art["decision_record"]),
            incident_register=str(art["incident_register"]),
        ),
        acceptance=AcceptanceSpec(**{k: bool(v) for k, v in acc.items()}),
    )
    _validate(spec)
    return spec


def _validate(spec: ProspectiveSpec) -> None:
    if spec.schema_version != "m7-prospective-v2":
        raise ValueError("M7 V2 requires schema_version='m7-prospective-v2'")
    if spec.core.prospective_start <= spec.core.protocol_freeze_date:
        raise ValueError("Prospective cohorts must start strictly after protocol freeze")
    if spec.core.target_horizon_days != 180:
        raise ValueError("ARGOS V1 prospective evaluation must preserve the frozen 180-day target")
    if spec.core.operating_mode != "shadow_human_review":
        raise ValueError("M7 V1 remains shadow + human review")
    if spec.cohorts.outcome_reporting_lag_days < 0:
        raise ValueError("outcome_reporting_lag_days cannot be negative")
    if spec.governance.allow_reuse_consumed_holdouts_for_selection:
        raise ValueError("TEST 2025 and OOT 2026 cannot be reused for selection")
    if not spec.governance.human_review_required:
        raise ValueError("Human review is mandatory in M7")
    if spec.governance.automatic_production_promotion:
        raise ValueError("M7 must not auto-promote a model to production")
    if not 0 < spec.performance.operational_fraction <= 1:
        raise ValueError("operational_fraction must be in (0, 1]")
    if not 0 < spec.performance.confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    if spec.performance.bootstrap_replicates < 100:
        raise ValueError("prospective bootstrap should use at least 100 replicates")
    if not spec.operations.terminal_review_statuses:
        raise ValueError("at least one terminal review status is required")
