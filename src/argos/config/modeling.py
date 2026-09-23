from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class ModelingRuntimeSpec:
    duckdb_threads: int
    duckdb_memory_limit: str | None


@dataclass(frozen=True, slots=True)
class PreprocessingSpec:
    missing_category: str
    onehot_max_categories: int
    onehot_min_frequency: int
    encoder_fit_max_rows: int


@dataclass(frozen=True, slots=True)
class LinearSpec:
    implementation: str
    epochs: int
    alpha: float
    positive_class_weight_cap: float


@dataclass(frozen=True, slots=True)
class BoostingSpec:
    implementation: str
    max_train_rows: int
    max_categories: int
    max_iter: int
    learning_rate: float
    max_leaf_nodes: int
    min_samples_leaf: int
    l2_regularization: float
    positive_class_weight_cap: float


@dataclass(frozen=True, slots=True)
class CalibrationSpec:
    fit_end: date
    selection_start: date
    methods: tuple[str, ...]
    min_partition_positives: int


@dataclass(frozen=True, slots=True)
class RankingSpec:
    review_fractions: tuple[float, ...]
    operational_fraction: float
    calibration_bins: int


@dataclass(frozen=True, slots=True)
class AblationSpec:
    max_train_rows: int
    max_iter: int
    families: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcceptanceSpec:
    min_validation_pr_auc_over_prevalence: float
    min_validation_lift_at_operational_k: float
    min_test_lift_at_operational_k: float


@dataclass(frozen=True, slots=True)
class TestPolicySpec:
    final_test_notebook: int
    reuse_completed_test_artifacts: bool


@dataclass(frozen=True, slots=True)
class ModelingSpec:
    schema_version: str
    model_matrix: str
    feature_registry: str
    target: str
    id_column: str
    t0_column: str
    split_column: str
    random_seed: int
    batch_size: int
    runtime: ModelingRuntimeSpec
    preprocessing: PreprocessingSpec
    linear: LinearSpec
    boosting: BoostingSpec
    calibration: CalibrationSpec
    ranking: RankingSpec
    ablation: AblationSpec
    acceptance: AcceptanceSpec
    test_policy: TestPolicySpec


def load_modeling_spec(path: Path) -> ModelingSpec:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    model = raw["modeling"]
    runtime = raw.get("runtime", {})
    pre = raw["preprocessing"]
    linear = raw["linear"]
    boost = raw["boosting"]
    calibration = raw["calibration"]
    ranking = raw["ranking"]
    ablation = raw["ablation"]
    acceptance = raw["acceptance"]
    test_policy = raw["test_policy"]

    spec = ModelingSpec(
        schema_version=str(model["schema_version"]),
        model_matrix=str(model["model_matrix"]),
        feature_registry=str(model["feature_registry"]),
        target=str(model["target"]),
        id_column=str(model["id_column"]),
        t0_column=str(model["t0_column"]),
        split_column=str(model["split_column"]),
        random_seed=int(model.get("random_seed", 42)),
        batch_size=int(model.get("batch_size", 100_000)),
        runtime=ModelingRuntimeSpec(
            duckdb_threads=max(1, int(runtime.get("duckdb_threads", 2))),
            duckdb_memory_limit=(str(runtime["duckdb_memory_limit"]) if runtime.get("duckdb_memory_limit") else None),
        ),
        preprocessing=PreprocessingSpec(
            missing_category=str(pre.get("missing_category", "__MISSING__")),
            onehot_max_categories=int(pre.get("onehot_max_categories", 128)),
            onehot_min_frequency=int(pre.get("onehot_min_frequency", 500)),
            encoder_fit_max_rows=int(pre.get("encoder_fit_max_rows", 250_000)),
        ),
        linear=LinearSpec(
            implementation=str(linear.get("implementation", "sgd_logistic")),
            epochs=int(linear.get("epochs", 2)),
            alpha=float(linear.get("alpha", 1e-5)),
            positive_class_weight_cap=float(linear.get("positive_class_weight_cap", 75.0)),
        ),
        boosting=BoostingSpec(
            implementation=str(boost.get("implementation", "hist_gradient_boosting")),
            max_train_rows=int(boost.get("max_train_rows", 750_000)),
            max_categories=int(boost.get("max_categories", 128)),
            max_iter=int(boost.get("max_iter", 220)),
            learning_rate=float(boost.get("learning_rate", 0.06)),
            max_leaf_nodes=int(boost.get("max_leaf_nodes", 31)),
            min_samples_leaf=int(boost.get("min_samples_leaf", 40)),
            l2_regularization=float(boost.get("l2_regularization", 1.0)),
            positive_class_weight_cap=float(boost.get("positive_class_weight_cap", 75.0)),
        ),
        calibration=CalibrationSpec(
            fit_end=date.fromisoformat(str(calibration["fit_end"])),
            selection_start=date.fromisoformat(str(calibration["selection_start"])),
            methods=tuple(str(v) for v in calibration.get("methods", ["none", "sigmoid", "isotonic"])),
            min_partition_positives=int(calibration.get("min_partition_positives", 500)),
        ),
        ranking=RankingSpec(
            review_fractions=tuple(float(v) for v in ranking["review_fractions"]),
            operational_fraction=float(ranking["operational_fraction"]),
            calibration_bins=int(ranking.get("calibration_bins", 15)),
        ),
        ablation=AblationSpec(
            max_train_rows=int(ablation.get("max_train_rows", 300_000)),
            max_iter=int(ablation.get("max_iter", 100)),
            families=tuple(str(v) for v in ablation.get("families", ["contract", "contract_historical", "all"])),
        ),
        acceptance=AcceptanceSpec(
            min_validation_pr_auc_over_prevalence=float(acceptance.get("min_validation_pr_auc_over_prevalence", 1.0)),
            min_validation_lift_at_operational_k=float(acceptance.get("min_validation_lift_at_operational_k", 1.0)),
            min_test_lift_at_operational_k=float(acceptance.get("min_test_lift_at_operational_k", 1.0)),
        ),
        test_policy=TestPolicySpec(
            final_test_notebook=int(test_policy.get("final_test_notebook", 36)),
            reuse_completed_test_artifacts=bool(test_policy.get("reuse_completed_test_artifacts", True)),
        ),
    )
    _validate(spec)
    return spec


def _validate(spec: ModelingSpec) -> None:
    if spec.schema_version != "m4-model-v1":
        raise ValueError("M4 V1 requires schema_version='m4-model-v1'")
    if not spec.ranking.review_fractions:
        raise ValueError("At least one review fraction is required")
    if not all(0.0 < x <= 1.0 for x in spec.ranking.review_fractions):
        raise ValueError("ranking.review_fractions must be in (0, 1]")
    if spec.ranking.operational_fraction not in spec.ranking.review_fractions:
        raise ValueError("operational_fraction must be present in review_fractions")
    if spec.calibration.fit_end >= spec.calibration.selection_start:
        raise ValueError("Calibration fit period must end before selection period starts")
    if spec.test_policy.final_test_notebook != 36:
        raise ValueError("M4 V1 freezes final TEST consumption to notebook 36")
