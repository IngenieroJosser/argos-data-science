from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class M6CoreSpec:
    schema_version: str
    model_version: str
    benchmark_gold_schema: str
    benchmark_model_schema: str
    benchmark_robustness_schema: str
    operating_mode: str
    scoring_mode: str
    human_review_required: bool
    batch_size: int


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    python_major_minor: str
    scikit_learn: str
    lockfile: str


@dataclass(frozen=True, slots=True)
class RegistrySpec:
    selection_manifest: str
    model_artifact: str
    calibrator_artifact: str
    model_card: str
    robustness_card: str
    monitoring_spec: str
    registry_record: str
    allowed_stages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataContractSpec:
    feature_registry: str
    id_column: str
    t0_column: str
    forbid_target_in_output: bool
    reject_duplicate_ids: bool
    reject_missing_ids: bool
    reject_missing_t0: bool
    contract_artifact: str


@dataclass(frozen=True, slots=True)
class ScoringSpec:
    operational_review_fraction: float
    tie_break: tuple[str, ...]
    output_root: str
    queue_root: str


@dataclass(frozen=True, slots=True)
class MonitoringSpec:
    reference_matrix: str
    reference_start: date
    reference_end: date
    reference_sample_rows: int
    numeric_bins: int
    numeric_feature_psi_warning: float
    numeric_feature_psi_high: float
    categorical_feature_tvd_warning: float
    categorical_feature_tvd_high: float
    score_psi_warning: float
    score_psi_high: float
    feature_missingness_absolute_delta_warning: float
    pause_on_high_alert: bool


@dataclass(frozen=True, slots=True)
class AuditSpec:
    log_path: str
    hash_chain: bool


@dataclass(frozen=True, slots=True)
class DeploymentSpec:
    default_stage: str
    shadow_stage: str
    allow_production_promotion: bool
    rollback_target: str
    state_path: str


@dataclass(frozen=True, slots=True)
class SecuritySpec:
    pii_forbidden_in_scoring_output: bool
    sensitive_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcceptanceSpec:
    min_required_feature_count: int
    max_registry_hash_mismatches: int
    require_idempotent_batch_scoring: bool
    require_hash_chained_audit: bool
    require_rollback_drill: bool
    require_human_review_queue: bool


@dataclass(frozen=True, slots=True)
class ProductionSpec:
    core: M6CoreSpec
    runtime: RuntimeSpec
    registry: RegistrySpec
    data_contract: DataContractSpec
    scoring: ScoringSpec
    monitoring: MonitoringSpec
    audit: AuditSpec
    deployment: DeploymentSpec
    security: SecuritySpec
    acceptance: AcceptanceSpec

    @property
    def schema_version(self) -> str:
        return self.core.schema_version


def load_production_spec(path: Path) -> ProductionSpec:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    core = raw["m6"]
    runtime = raw["runtime"]
    registry = raw["registry"]
    contract = raw["data_contract"]
    scoring = raw["scoring"]
    monitoring = raw["monitoring"]
    audit = raw["audit"]
    deployment = raw["deployment"]
    security = raw["security"]
    acceptance = raw["acceptance"]

    spec = ProductionSpec(
        core=M6CoreSpec(
            schema_version=str(core["schema_version"]),
            model_version=str(core["model_version"]),
            benchmark_gold_schema=str(core["benchmark_gold_schema"]),
            benchmark_model_schema=str(core["benchmark_model_schema"]),
            benchmark_robustness_schema=str(core["benchmark_robustness_schema"]),
            operating_mode=str(core["operating_mode"]),
            scoring_mode=str(core["scoring_mode"]),
            human_review_required=bool(core["human_review_required"]),
            batch_size=int(core["batch_size"]),
        ),
        runtime=RuntimeSpec(
            python_major_minor=str(runtime["python_major_minor"]),
            scikit_learn=str(runtime["scikit_learn"]),
            lockfile=str(runtime["lockfile"]),
        ),
        registry=RegistrySpec(
            selection_manifest=str(registry["selection_manifest"]),
            model_artifact=str(registry["model_artifact"]),
            calibrator_artifact=str(registry["calibrator_artifact"]),
            model_card=str(registry["model_card"]),
            robustness_card=str(registry["robustness_card"]),
            monitoring_spec=str(registry["monitoring_spec"]),
            registry_record=str(registry["registry_record"]),
            allowed_stages=tuple(str(v) for v in registry["allowed_stages"]),
        ),
        data_contract=DataContractSpec(
            feature_registry=str(contract["feature_registry"]),
            id_column=str(contract["id_column"]),
            t0_column=str(contract["t0_column"]),
            forbid_target_in_output=bool(contract["forbid_target_in_output"]),
            reject_duplicate_ids=bool(contract["reject_duplicate_ids"]),
            reject_missing_ids=bool(contract["reject_missing_ids"]),
            reject_missing_t0=bool(contract["reject_missing_t0"]),
            contract_artifact=str(contract["contract_artifact"]),
        ),
        scoring=ScoringSpec(
            operational_review_fraction=float(scoring["operational_review_fraction"]),
            tie_break=tuple(str(v) for v in scoring["tie_break"]),
            output_root=str(scoring["output_root"]),
            queue_root=str(scoring["queue_root"]),
        ),
        monitoring=MonitoringSpec(
            reference_matrix=str(monitoring["reference_matrix"]),
            reference_start=date.fromisoformat(str(monitoring["reference_start"])),
            reference_end=date.fromisoformat(str(monitoring["reference_end"])),
            reference_sample_rows=int(monitoring["reference_sample_rows"]),
            numeric_bins=int(monitoring["numeric_bins"]),
            numeric_feature_psi_warning=float(monitoring["numeric_feature_psi_warning"]),
            numeric_feature_psi_high=float(monitoring["numeric_feature_psi_high"]),
            categorical_feature_tvd_warning=float(monitoring["categorical_feature_tvd_warning"]),
            categorical_feature_tvd_high=float(monitoring["categorical_feature_tvd_high"]),
            score_psi_warning=float(monitoring["score_psi_warning"]),
            score_psi_high=float(monitoring["score_psi_high"]),
            feature_missingness_absolute_delta_warning=float(monitoring["feature_missingness_absolute_delta_warning"]),
            pause_on_high_alert=bool(monitoring["pause_on_high_alert"]),
        ),
        audit=AuditSpec(log_path=str(audit["log_path"]), hash_chain=bool(audit["hash_chain"])),
        deployment=DeploymentSpec(
            default_stage=str(deployment["default_stage"]),
            shadow_stage=str(deployment["shadow_stage"]),
            allow_production_promotion=bool(deployment["allow_production_promotion"]),
            rollback_target=str(deployment["rollback_target"]),
            state_path=str(deployment["state_path"]),
        ),
        security=SecuritySpec(
            pii_forbidden_in_scoring_output=bool(security["pii_forbidden_in_scoring_output"]),
            sensitive_columns=tuple(str(v) for v in security["sensitive_columns"]),
        ),
        acceptance=AcceptanceSpec(
            min_required_feature_count=int(acceptance["min_required_feature_count"]),
            max_registry_hash_mismatches=int(acceptance["max_registry_hash_mismatches"]),
            require_idempotent_batch_scoring=bool(acceptance["require_idempotent_batch_scoring"]),
            require_hash_chained_audit=bool(acceptance["require_hash_chained_audit"]),
            require_rollback_drill=bool(acceptance["require_rollback_drill"]),
            require_human_review_queue=bool(acceptance["require_human_review_queue"]),
        ),
    )
    _validate(spec)
    return spec


def _validate(spec: ProductionSpec) -> None:
    if spec.schema_version != "m6-production-v1":
        raise ValueError("M6 V1 requires schema_version='m6-production-v1'")
    if spec.core.operating_mode != "shadow":
        raise ValueError("M6 V1 starts in shadow mode")
    if spec.core.scoring_mode != "batch":
        raise ValueError("M6 V1 is batch-first; online serving is not justified by the current use case")
    if not spec.core.human_review_required:
        raise ValueError("ARGOS requires human review after model prioritization")
    if spec.scoring.tie_break != ("score_desc", "raw_score_desc", "contract_id_asc"):
        raise ValueError("M6 must preserve the deterministic M5 ranking contract")
    if spec.deployment.allow_production_promotion:
        raise ValueError("This M6 package must not pre-authorize production promotion")
    if "shadow" not in spec.registry.allowed_stages or "paused" not in spec.registry.allowed_stages:
        raise ValueError("Registry stages must support shadow and paused states")
    if not 0.0 < spec.scoring.operational_review_fraction <= 1.0:
        raise ValueError("operational_review_fraction must be in (0, 1]")
