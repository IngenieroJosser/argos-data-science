from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class M8CoreSpec:
    schema_version: str
    development_model_version: str
    base_model_version: str


@dataclass(frozen=True, slots=True)
class AdvancedGovernanceSpec:
    require_m6_closed: bool
    require_m7_protocol_frozen: bool
    allow_consumed_holdouts_for_selection: bool
    consumed_holdout_years: tuple[int, ...]
    development_splits: tuple[str, ...]
    max_future_feature_violations: int
    human_review_required: bool


@dataclass(frozen=True, slots=True)
class NLPSpec:
    enabled: bool
    text_columns: tuple[str, ...]
    embedding_backend: str
    model_name: str
    model_revision: str
    index_backend: str
    allow_fallback_for_gate: bool
    fallback_backend: str
    min_text_chars: int
    batch_size: int
    neighbor_k: int
    min_neighbors: int
    svd_components: int
    random_seed: int


@dataclass(frozen=True, slots=True)
class GraphSpec:
    enabled: bool
    snapshot_frequency: str
    pagerank_alpha: float
    pagerank_tolerance: float
    pagerank_max_iter: int
    pagerank_refresh_months: int
    max_bidders_per_process: int
    publication_time_column: str
    require_publication_timestamp: bool


@dataclass(frozen=True, slots=True)
class AnomalySpec:
    enabled: bool
    implementation: str
    max_train_rows: int
    n_estimators: int
    max_samples: int
    contamination: str
    random_seed: int


@dataclass(frozen=True, slots=True)
class SurvivalSpec:
    enabled: bool
    horizon_days: int
    evaluation_horizons: tuple[int, ...]
    max_train_rows: int
    max_validation_rows: int
    min_total_events: int
    min_train_events: int
    min_validation_events: int
    l2_penalty: float
    max_iter: int
    tolerance: float
    calibration_bins: int
    ph_diagnostic_top_k: int
    random_seed: int


@dataclass(frozen=True, slots=True)
class M8AblationSpec:
    max_train_rows: int
    max_iter: int
    families: tuple[str, ...]
    validation_role: str
    operational_fraction: float
    min_pr_auc_relative_gain: float
    min_lift_relative_gain: float


@dataclass(frozen=True, slots=True)
class M8ArtifactSpec:
    semantic_features: str
    graph_features: str
    anomaly_features: str
    development_matrix: str
    anomaly_model: str
    selected_model: str
    survival_outcomes: str
    survival_model: str
    semantic_manifest: str
    graph_manifest: str
    anomaly_manifest: str
    survival_outcomes_manifest: str
    survival_manifest: str
    ablation_manifest: str
    pit_manifest: str
    selection_manifest: str


@dataclass(frozen=True, slots=True)
class M8AcceptanceSpec:
    require_semantic_backend: bool
    require_graph_pit: bool
    require_anomaly_train_only_fit: bool
    require_temporal_ablation: bool
    require_survival_analysis: bool
    require_m7_hash_integrity: bool
    require_no_consumed_holdout_selection: bool
    require_explicit_feature_selection: bool


@dataclass(frozen=True, slots=True)
class AdvancedSpec:
    core: M8CoreSpec
    governance: AdvancedGovernanceSpec
    nlp: NLPSpec
    graph: GraphSpec
    anomaly: AnomalySpec
    survival: SurvivalSpec
    ablation: M8AblationSpec
    artifacts: M8ArtifactSpec
    acceptance: M8AcceptanceSpec

    @property
    def schema_version(self) -> str:
        return self.core.schema_version


def load_advanced_spec(path: Path) -> AdvancedSpec:
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)

    m8 = raw["m8"]
    gov = raw["governance"]
    nlp = raw["nlp"]
    graph = raw["graph"]
    anomaly = raw["anomaly"]
    survival = raw["survival"]
    ablation = raw["ablation"]
    artifacts = raw["artifacts"]
    acceptance = raw["acceptance"]

    spec = AdvancedSpec(
        core=M8CoreSpec(
            schema_version=str(m8["schema_version"]),
            development_model_version=str(m8["development_model_version"]),
            base_model_version=str(m8["base_model_version"]),
        ),
        governance=AdvancedGovernanceSpec(
            require_m6_closed=bool(gov["require_m6_closed"]),
            require_m7_protocol_frozen=bool(gov["require_m7_protocol_frozen"]),
            allow_consumed_holdouts_for_selection=bool(
                gov["allow_consumed_holdouts_for_selection"]
            ),
            consumed_holdout_years=tuple(int(v) for v in gov["consumed_holdout_years"]),
            development_splits=tuple(str(v) for v in gov["development_splits"]),
            max_future_feature_violations=int(gov["max_future_feature_violations"]),
            human_review_required=bool(gov["human_review_required"]),
        ),
        nlp=NLPSpec(
            enabled=bool(nlp["enabled"]),
            text_columns=tuple(str(v) for v in nlp["text_columns"]),
            embedding_backend=str(nlp["embedding_backend"]),
            model_name=str(nlp["model_name"]),
            model_revision=str(nlp.get("model_revision", "")),
            index_backend=str(nlp["index_backend"]),
            allow_fallback_for_gate=bool(nlp["allow_fallback_for_gate"]),
            fallback_backend=str(nlp["fallback_backend"]),
            min_text_chars=int(nlp["min_text_chars"]),
            batch_size=int(nlp["batch_size"]),
            neighbor_k=int(nlp["neighbor_k"]),
            min_neighbors=int(nlp["min_neighbors"]),
            svd_components=int(nlp["svd_components"]),
            random_seed=int(nlp["random_seed"]),
        ),
        graph=GraphSpec(
            enabled=bool(graph["enabled"]),
            snapshot_frequency=str(graph["snapshot_frequency"]),
            pagerank_alpha=float(graph["pagerank_alpha"]),
            pagerank_tolerance=float(graph["pagerank_tolerance"]),
            pagerank_max_iter=int(graph["pagerank_max_iter"]),
            pagerank_refresh_months=int(graph["pagerank_refresh_months"]),
            max_bidders_per_process=int(graph["max_bidders_per_process"]),
            publication_time_column=str(graph["publication_time_column"]),
            require_publication_timestamp=bool(graph["require_publication_timestamp"]),
        ),
        anomaly=AnomalySpec(
            enabled=bool(anomaly["enabled"]),
            implementation=str(anomaly["implementation"]),
            max_train_rows=int(anomaly["max_train_rows"]),
            n_estimators=int(anomaly["n_estimators"]),
            max_samples=int(anomaly["max_samples"]),
            contamination=str(anomaly["contamination"]),
            random_seed=int(anomaly["random_seed"]),
        ),
        survival=SurvivalSpec(
            enabled=bool(survival["enabled"]),
            horizon_days=int(survival["horizon_days"]),
            evaluation_horizons=tuple(int(v) for v in survival["evaluation_horizons"]),
            max_train_rows=int(survival["max_train_rows"]),
            max_validation_rows=int(survival["max_validation_rows"]),
            min_total_events=int(survival["min_total_events"]),
            min_train_events=int(survival["min_train_events"]),
            min_validation_events=int(survival["min_validation_events"]),
            l2_penalty=float(survival["l2_penalty"]),
            max_iter=int(survival["max_iter"]),
            tolerance=float(survival["tolerance"]),
            calibration_bins=int(survival["calibration_bins"]),
            ph_diagnostic_top_k=int(survival["ph_diagnostic_top_k"]),
            random_seed=int(survival["random_seed"]),
        ),
        ablation=M8AblationSpec(
            max_train_rows=int(ablation["max_train_rows"]),
            max_iter=int(ablation["max_iter"]),
            families=tuple(str(v) for v in ablation["families"]),
            validation_role=str(ablation["validation_role"]),
            operational_fraction=float(ablation["operational_fraction"]),
            min_pr_auc_relative_gain=float(ablation["min_pr_auc_relative_gain"]),
            min_lift_relative_gain=float(ablation["min_lift_relative_gain"]),
        ),
        artifacts=M8ArtifactSpec(**{k: str(v) for k, v in artifacts.items()}),
        acceptance=M8AcceptanceSpec(**{k: bool(v) for k, v in acceptance.items()}),
    )
    _validate(spec)
    return spec


def _validate(spec: AdvancedSpec) -> None:
    if spec.schema_version != "m8-advanced-intelligence-v2":
        raise ValueError("M8 requires schema_version='m8-advanced-intelligence-v2'")
    if spec.governance.allow_consumed_holdouts_for_selection:
        raise ValueError("M8 cannot reuse consumed TEST/OOT holdouts for selection")
    if set(spec.governance.development_splits) - {"train", "validation"}:
        raise ValueError("M8 development_splits may contain only train/validation")
    if not spec.nlp.text_columns:
        raise ValueError("M8 NLP requires at least one text column")
    if spec.nlp.min_neighbors < 1 or spec.nlp.neighbor_k < spec.nlp.min_neighbors:
        raise ValueError("Invalid semantic neighbor configuration")
    if spec.graph.snapshot_frequency != "month":
        raise ValueError("M8 V1 supports graph.snapshot_frequency='month' only")
    if not 0 < spec.graph.pagerank_alpha < 1:
        raise ValueError("graph.pagerank_alpha must be in (0,1)")
    if spec.anomaly.implementation != "isolation_forest":
        raise ValueError("M8 supports only isolation_forest anomalies")
    if not spec.survival.enabled:
        raise ValueError("M8 closure requires survival analysis enabled")
    if spec.survival.horizon_days <= 0:
        raise ValueError("survival.horizon_days must be > 0")
    horizons = spec.survival.evaluation_horizons
    if not horizons or tuple(sorted(horizons)) != horizons:
        raise ValueError("survival.evaluation_horizons must be non-empty and ordered")
    if horizons[-1] != spec.survival.horizon_days:
        raise ValueError("survival evaluation must include the administrative horizon")
    if any(value <= 0 or value > spec.survival.horizon_days for value in horizons):
        raise ValueError("survival evaluation horizons must be inside the target horizon")
    if spec.survival.max_train_rows <= 0 or spec.survival.max_validation_rows <= 0:
        raise ValueError("survival sample caps must be > 0")
    if spec.survival.l2_penalty < 0:
        raise ValueError("survival.l2_penalty must be >= 0")
    if not 0 < spec.ablation.operational_fraction <= 1:
        raise ValueError("M8 ablation operational_fraction must be in (0,1]")
