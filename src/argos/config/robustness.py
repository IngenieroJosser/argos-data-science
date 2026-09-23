from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class M5CoreSpec:
    schema_version: str
    benchmark_gold_schema: str
    benchmark_model_schema: str
    benchmark_model_name: str
    benchmark_calibration: str
    random_seed: int
    batch_size: int


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    duckdb_threads: int
    duckdb_memory_limit: str | None


@dataclass(frozen=True, slots=True)
class BacktestingSpec:
    evaluation_years: tuple[int, ...]
    max_train_rows: int
    max_iter: int
    min_training_rows: int
    min_evaluation_rows: int
    min_evaluation_positives: int
    operational_fraction: float


@dataclass(frozen=True, slots=True)
class ExplainabilitySpec:
    validation_start: date
    validation_end: date
    sample_rows: int
    permutation_repeats: int
    local_case_count: int
    min_global_features_reported: int


@dataclass(frozen=True, slots=True)
class UncertaintySpec:
    sample_rows: int
    validation_start: date
    validation_end: date
    bootstrap_replicates: int
    confidence_level: float
    operational_fraction: float


@dataclass(frozen=True, slots=True)
class DriftSpec:
    reference_start: date
    reference_end: date
    monitor_start: date
    monitor_end: date
    sample_rows_per_period: int
    numeric_bins: int
    psi_warning: float
    psi_high: float
    categorical_tvd_warning: float
    categorical_tvd_high: float


@dataclass(frozen=True, slots=True)
class FeatureValueSpec:
    evaluation_years: tuple[int, ...]
    max_train_rows: int
    max_iter: int
    families: tuple[str, ...]
    operational_fraction: float


@dataclass(frozen=True, slots=True)
class FreshOOTSpec:
    start: date
    max_end: date
    min_rows: int
    min_positives: int
    operational_fraction: float
    reuse_completed_artifacts: bool


@dataclass(frozen=True, slots=True)
class RankingRobustnessSpec:
    tie_break: tuple[str, ...]
    review_fractions: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class M5AcceptanceSpec:
    min_backtest_folds: int
    min_backtest_lift_at_operational_k: float
    min_fresh_oot_pr_auc_over_prevalence: float
    min_fresh_oot_lift_at_operational_k: float
    max_model_hash_mismatches: int


@dataclass(frozen=True, slots=True)
class GovernanceSpec:
    consumed_test_year: int
    fresh_oot_year: int
    production_authorized: bool




@dataclass(frozen=True, slots=True)
class MonitoringSpec:
    prevalence_relative_change_warning: float
    score_psi_warning: float
    score_psi_high: float
    top_k_lift_floor: float
    tail_calibration_abs_gap_warning: float
    feature_missingness_absolute_delta_warning: float


@dataclass(frozen=True, slots=True)
class RobustnessSpec:
    core: M5CoreSpec
    runtime: RuntimeSpec
    backtesting: BacktestingSpec
    explainability: ExplainabilitySpec
    uncertainty: UncertaintySpec
    drift: DriftSpec
    feature_value: FeatureValueSpec
    fresh_oot: FreshOOTSpec
    ranking: RankingRobustnessSpec
    acceptance: M5AcceptanceSpec
    governance: GovernanceSpec
    monitoring: MonitoringSpec

    @property
    def schema_version(self) -> str:
        return self.core.schema_version


def load_robustness_spec(path: Path) -> RobustnessSpec:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    core = raw["m5"]
    runtime = raw.get("runtime", {})
    back = raw["backtesting"]
    explain = raw["explainability"]
    uncertainty = raw["uncertainty"]
    drift = raw["drift"]
    feature_value = raw["feature_value"]
    fresh = raw["fresh_oot"]
    ranking = raw["ranking"]
    acceptance = raw["acceptance"]
    governance = raw["governance"]
    monitoring = raw["monitoring"]

    spec = RobustnessSpec(
        core=M5CoreSpec(
            schema_version=str(core["schema_version"]),
            benchmark_gold_schema=str(core["benchmark_gold_schema"]),
            benchmark_model_schema=str(core["benchmark_model_schema"]),
            benchmark_model_name=str(core["benchmark_model_name"]),
            benchmark_calibration=str(core["benchmark_calibration"]),
            random_seed=int(core.get("random_seed", 42)),
            batch_size=int(core.get("batch_size", 100_000)),
        ),
        runtime=RuntimeSpec(
            duckdb_threads=max(1, int(runtime.get("duckdb_threads", 2))),
            duckdb_memory_limit=(str(runtime["duckdb_memory_limit"]) if runtime.get("duckdb_memory_limit") else None),
        ),
        backtesting=BacktestingSpec(
            evaluation_years=tuple(int(v) for v in back["evaluation_years"]),
            max_train_rows=int(back["max_train_rows"]),
            max_iter=int(back["max_iter"]),
            min_training_rows=int(back["min_training_rows"]),
            min_evaluation_rows=int(back["min_evaluation_rows"]),
            min_evaluation_positives=int(back["min_evaluation_positives"]),
            operational_fraction=float(back["operational_fraction"]),
        ),
        explainability=ExplainabilitySpec(
            validation_start=date.fromisoformat(str(explain["validation_start"])),
            validation_end=date.fromisoformat(str(explain["validation_end"])),
            sample_rows=int(explain["sample_rows"]),
            permutation_repeats=int(explain["permutation_repeats"]),
            local_case_count=int(explain["local_case_count"]),
            min_global_features_reported=int(explain["min_global_features_reported"]),
        ),
        uncertainty=UncertaintySpec(
            sample_rows=int(uncertainty.get("sample_rows", 100_000)),
            validation_start=date.fromisoformat(str(uncertainty["validation_start"])),
            validation_end=date.fromisoformat(str(uncertainty["validation_end"])),
            bootstrap_replicates=int(uncertainty["bootstrap_replicates"]),
            confidence_level=float(uncertainty["confidence_level"]),
            operational_fraction=float(uncertainty["operational_fraction"]),
        ),
        drift=DriftSpec(
            reference_start=date.fromisoformat(str(drift["reference_start"])),
            reference_end=date.fromisoformat(str(drift["reference_end"])),
            monitor_start=date.fromisoformat(str(drift["monitor_start"])),
            monitor_end=date.fromisoformat(str(drift["monitor_end"])),
            sample_rows_per_period=int(drift["sample_rows_per_period"]),
            numeric_bins=int(drift["numeric_bins"]),
            psi_warning=float(drift["psi_warning"]),
            psi_high=float(drift["psi_high"]),
            categorical_tvd_warning=float(drift["categorical_tvd_warning"]),
            categorical_tvd_high=float(drift["categorical_tvd_high"]),
        ),
        feature_value=FeatureValueSpec(
            evaluation_years=tuple(int(v) for v in feature_value["evaluation_years"]),
            max_train_rows=int(feature_value["max_train_rows"]),
            max_iter=int(feature_value["max_iter"]),
            families=tuple(str(v) for v in feature_value["families"]),
            operational_fraction=float(feature_value["operational_fraction"]),
        ),
        fresh_oot=FreshOOTSpec(
            start=date.fromisoformat(str(fresh["start"])),
            max_end=date.fromisoformat(str(fresh["max_end"])),
            min_rows=int(fresh["min_rows"]),
            min_positives=int(fresh["min_positives"]),
            operational_fraction=float(fresh["operational_fraction"]),
            reuse_completed_artifacts=bool(fresh.get("reuse_completed_artifacts", True)),
        ),
        ranking=RankingRobustnessSpec(
            tie_break=tuple(str(v) for v in ranking["tie_break"]),
            review_fractions=tuple(float(v) for v in ranking["review_fractions"]),
        ),
        acceptance=M5AcceptanceSpec(
            min_backtest_folds=int(acceptance["min_backtest_folds"]),
            min_backtest_lift_at_operational_k=float(acceptance["min_backtest_lift_at_operational_k"]),
            min_fresh_oot_pr_auc_over_prevalence=float(acceptance["min_fresh_oot_pr_auc_over_prevalence"]),
            min_fresh_oot_lift_at_operational_k=float(acceptance["min_fresh_oot_lift_at_operational_k"]),
            max_model_hash_mismatches=int(acceptance["max_model_hash_mismatches"]),
        ),
        governance=GovernanceSpec(
            consumed_test_year=int(governance["consumed_test_year"]),
            fresh_oot_year=int(governance["fresh_oot_year"]),
            production_authorized=bool(governance.get("production_authorized", False)),
        ),
        monitoring=MonitoringSpec(
            prevalence_relative_change_warning=float(monitoring["prevalence_relative_change_warning"]),
            score_psi_warning=float(monitoring["score_psi_warning"]),
            score_psi_high=float(monitoring["score_psi_high"]),
            top_k_lift_floor=float(monitoring["top_k_lift_floor"]),
            tail_calibration_abs_gap_warning=float(monitoring["tail_calibration_abs_gap_warning"]),
            feature_missingness_absolute_delta_warning=float(monitoring["feature_missingness_absolute_delta_warning"]),
        ),
    )
    _validate(spec)
    return spec


def _validate(spec: RobustnessSpec) -> None:
    if spec.schema_version != "m5-robustness-v1":
        raise ValueError("M5 V1 requires schema_version='m5-robustness-v1'")
    years = spec.backtesting.evaluation_years
    if not years or tuple(sorted(set(years))) != years:
        raise ValueError("backtesting.evaluation_years must be unique and increasing")
    if spec.governance.consumed_test_year in years:
        raise ValueError("Consumed TEST year cannot be used as an M5 development backtest fold")
    if spec.governance.fresh_oot_year <= spec.governance.consumed_test_year:
        raise ValueError("Fresh OOT year must be strictly later than the consumed TEST year")
    if not 0.0 < spec.uncertainty.confidence_level < 1.0:
        raise ValueError("uncertainty.confidence_level must be in (0, 1)")
    if spec.uncertainty.bootstrap_replicates < 50:
        raise ValueError("At least 50 bootstrap replicates are required")
    if spec.ranking.tie_break != ("score_desc", "raw_score_desc", "contract_id_asc"):
        raise ValueError("M5 V1 freezes deterministic ranking tie-break to score/raw_score/contract_id")
    if spec.fresh_oot.start.year != spec.governance.fresh_oot_year:
        raise ValueError("fresh_oot.start must belong to the configured fresh OOT year")
    if spec.governance.production_authorized:
        raise ValueError("M5 code package must not pre-authorize production")
