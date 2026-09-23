from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class GoldRuntimeSpec:
    duckdb_threads: int
    duckdb_memory_limit: str | None


@dataclass(frozen=True, slots=True)
class TargetGoldSpec:
    name: str
    t0_column: str
    horizon_days: int
    included_event_types: tuple[str, ...]
    label_cutoff_strategy: str
    min_t0_coverage: float
    min_eligible_rows: int
    min_positive_rows: int
    min_prevalence: float
    max_prevalence: float
    plausible_year_min: int
    plausible_year_max: int


@dataclass(frozen=True, slots=True)
class TemporalSplitSpec:
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date
    min_train_rows: int
    min_validation_rows: int
    min_test_rows: int
    min_positive_rows_per_split: int


@dataclass(frozen=True, slots=True)
class ContractFeatureSpec:
    categorical_candidates: tuple[str, ...]
    numeric_candidates: tuple[str, ...]
    required_identity_columns: tuple[str, ...]
    forbidden_columns: tuple[str, ...]
    min_selected_features: int


@dataclass(frozen=True, slots=True)
class HistoricalFeatureSpec:
    entity_key: str
    supplier_key: str
    qualifying_event_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompetitionFeatureSpec:
    publication_time_column: str
    require_timestamp_for_pit: bool


@dataclass(frozen=True, slots=True)
class GoldValidationSpec:
    max_feature_future_violations: int
    max_duplicate_contract_rows: int
    require_all_assigned_rows_labeled: bool


@dataclass(frozen=True, slots=True)
class GoldSpec:
    schema_version: str
    compression: str
    row_group_size: int
    runtime: GoldRuntimeSpec
    target: TargetGoldSpec
    splits: TemporalSplitSpec
    contract_features: ContractFeatureSpec
    historical_features: HistoricalFeatureSpec
    competition_features: CompetitionFeatureSpec
    validation: GoldValidationSpec


def _as_date(value: str) -> date:
    return date.fromisoformat(str(value))


def _tuple_upper(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(value).strip().upper() for value in values)


def load_gold_spec(path: Path) -> GoldSpec:
    """Load the frozen M3 point-in-time analytical contract."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    gold = raw["gold"]
    runtime = gold.get("runtime", {})
    target = raw["target"]
    splits = raw["splits"]
    contract_features = raw["contract_features"]
    historical = raw["historical_features"]
    competition = raw["competition_features"]
    validation = raw["validation"]

    spec = GoldSpec(
        schema_version=str(gold["schema_version"]),
        compression=str(gold.get("compression", "zstd")),
        row_group_size=int(gold.get("row_group_size", 100_000)),
        runtime=GoldRuntimeSpec(
            duckdb_threads=max(1, int(runtime.get("duckdb_threads", 2))),
            duckdb_memory_limit=(
                str(runtime["duckdb_memory_limit"])
                if runtime.get("duckdb_memory_limit")
                else None
            ),
        ),
        target=TargetGoldSpec(
            name=str(target["name"]),
            t0_column=str(target["t0_column"]),
            horizon_days=int(target["horizon_days"]),
            included_event_types=_tuple_upper(target["included_event_types"]),
            label_cutoff_strategy=str(target.get("label_cutoff_strategy", "max_all_event_at")),
            min_t0_coverage=float(target.get("min_t0_coverage", 0.85)),
            min_eligible_rows=int(target.get("min_eligible_rows", 100_000)),
            min_positive_rows=int(target.get("min_positive_rows", 1_000)),
            min_prevalence=float(target.get("min_prevalence", 0.001)),
            max_prevalence=float(target.get("max_prevalence", 0.50)),
            plausible_year_min=int(target.get("plausible_year_min", 2000)),
            plausible_year_max=int(target.get("plausible_year_max", 2100)),
        ),
        splits=TemporalSplitSpec(
            train_start=_as_date(splits["train_start"]),
            train_end=_as_date(splits["train_end"]),
            validation_start=_as_date(splits["validation_start"]),
            validation_end=_as_date(splits["validation_end"]),
            test_start=_as_date(splits["test_start"]),
            test_end=_as_date(splits["test_end"]),
            min_train_rows=int(splits.get("min_train_rows", 100_000)),
            min_validation_rows=int(splits.get("min_validation_rows", 50_000)),
            min_test_rows=int(splits.get("min_test_rows", 50_000)),
            min_positive_rows_per_split=int(splits.get("min_positive_rows_per_split", 500)),
        ),
        contract_features=ContractFeatureSpec(
            categorical_candidates=tuple(str(v) for v in contract_features.get("categorical_candidates", [])),
            numeric_candidates=tuple(str(v) for v in contract_features.get("numeric_candidates", [])),
            required_identity_columns=tuple(str(v) for v in contract_features.get("required_identity_columns", [])),
            forbidden_columns=tuple(str(v) for v in contract_features.get("forbidden_columns", [])),
            min_selected_features=int(contract_features.get("min_selected_features", 5)),
        ),
        historical_features=HistoricalFeatureSpec(
            entity_key=str(historical.get("entity_key", "nit_entidad")),
            supplier_key=str(historical.get("supplier_key", "supplier_code")),
            qualifying_event_types=_tuple_upper(historical.get("qualifying_event_types", [])),
        ),
        competition_features=CompetitionFeatureSpec(
            publication_time_column=str(competition.get("publication_time_column", "publication_at")),
            require_timestamp_for_pit=bool(competition.get("require_timestamp_for_pit", True)),
        ),
        validation=GoldValidationSpec(
            max_feature_future_violations=int(validation.get("max_feature_future_violations", 0)),
            max_duplicate_contract_rows=int(validation.get("max_duplicate_contract_rows", 0)),
            require_all_assigned_rows_labeled=bool(validation.get("require_all_assigned_rows_labeled", True)),
        ),
    )
    _validate_spec(spec)
    return spec


def _validate_spec(spec: GoldSpec) -> None:
    if spec.target.horizon_days <= 0:
        raise ValueError("target.horizon_days must be > 0")
    if not spec.target.included_event_types:
        raise ValueError("target.included_event_types cannot be empty")
    if spec.target.label_cutoff_strategy != "max_all_event_at":
        raise ValueError("Only label_cutoff_strategy='max_all_event_at' is supported in M3 V1")
    s = spec.splits
    if not (
        s.train_start <= s.train_end < s.validation_start <= s.validation_end
        < s.test_start <= s.test_end
    ):
        raise ValueError("Temporal split periods must be strictly ordered and non-overlapping")
    overlap = set(spec.contract_features.forbidden_columns) & set(spec.contract_features.categorical_candidates)
    overlap |= set(spec.contract_features.forbidden_columns) & set(spec.contract_features.numeric_candidates)
    if overlap:
        raise ValueError(f"Forbidden columns cannot be configured as features: {sorted(overlap)}")
