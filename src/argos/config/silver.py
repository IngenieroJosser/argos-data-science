from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from argos.common.names import normalize_name


@dataclass(frozen=True, slots=True)
class ContractsSilverSpec:
    primary_key: str
    process_fk: str
    supplier_fk: str
    snapshot_state_columns: tuple[str, ...]
    excluded_semantic_types: tuple[str, ...]
    rename: dict[str, str]


@dataclass(frozen=True, slots=True)
class ProcessesSilverSpec:
    identity_key: str
    procedure_key: str
    reference_key: str
    excluded_semantic_types: tuple[str, ...]
    rename: dict[str, str]


@dataclass(frozen=True, slots=True)
class SuppliersSilverSpec:
    primary_key: str
    nit_key: str
    excluded_columns: tuple[str, ...]
    excluded_semantic_types: tuple[str, ...]
    rename: dict[str, str]


@dataclass(frozen=True, slots=True)
class BiddersSilverSpec:
    process_key: str
    supplier_code_candidate: str
    nit_candidate: str
    excluded_columns: tuple[str, ...]
    excluded_semantic_types: tuple[str, ...]
    rename: dict[str, str]


@dataclass(frozen=True, slots=True)
class AdditionsSilverSpec:
    contract_key: str
    event_time: str
    event_type: str
    identifier: str
    description: str
    rename: dict[str, str]


@dataclass(frozen=True, slots=True)
class EntityResolutionSpec:
    code_strategy_enabled: bool
    nit_strategy_enabled: bool
    report_min_resolved_coverage: float


@dataclass(frozen=True, slots=True)
class SilverValidationSpec:
    contracts_processes_min_coverage: float
    bidders_processes_min_coverage: float
    additions_contracts_min_coverage: float
    t0_column: str
    t0_min_parse_success_nonnull: float
    addition_event_min_parse_success_nonnull: float


@dataclass(frozen=True, slots=True)
class SilverRuntimeSpec:
    duckdb_threads: int
    duckdb_memory_limit: str | None


@dataclass(frozen=True, slots=True)
class SilverSpec:
    schema_version: str
    compression: str
    row_group_size: int
    runtime: SilverRuntimeSpec
    contracts: ContractsSilverSpec
    processes: ProcessesSilverSpec
    suppliers: SuppliersSilverSpec
    bidders: BiddersSilverSpec
    additions: AdditionsSilverSpec
    entity_resolution: EntityResolutionSpec
    validation: SilverValidationSpec


def _normalized_rename(values: dict[str, str]) -> dict[str, str]:
    return {
        normalize_name(source): normalize_name(target)
        for source, target in values.items()
    }


def _normalized_values(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(normalize_name(value) for value in values)


def load_silver_spec(path: Path) -> SilverSpec:
    """Load the frozen M2 Silver transformation contract.

    The config centralizes domain decisions for notebooks 10–15. Notebook code
    orchestrates and inspects; transformation semantics live in ``src/argos``.
    """
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    silver = raw["silver"]
    runtime = silver.get("runtime", {})
    contracts = raw["contracts"]
    processes = raw["processes"]
    suppliers = raw.get("suppliers", {})
    bidders = raw.get("bidders", {})
    additions = raw.get("additions", {})
    entity_resolution = raw.get("entity_resolution", {})
    validation = raw["validation"]

    return SilverSpec(
        schema_version=str(silver["schema_version"]),
        compression=str(silver.get("compression", "zstd")),
        row_group_size=int(silver.get("row_group_size", 100_000)),
        runtime=SilverRuntimeSpec(
            duckdb_threads=max(1, int(runtime.get("duckdb_threads", 2))),
            duckdb_memory_limit=(
                str(runtime["duckdb_memory_limit"])
                if runtime.get("duckdb_memory_limit")
                else None
            ),
        ),
        contracts=ContractsSilverSpec(
            primary_key=normalize_name(contracts["primary_key"]),
            process_fk=normalize_name(contracts["process_fk"]),
            supplier_fk=normalize_name(contracts["supplier_fk"]),
            snapshot_state_columns=_normalized_values(
                contracts.get("snapshot_state_columns", [])
            ),
            excluded_semantic_types=tuple(
                str(value) for value in contracts.get("excluded_semantic_types", [])
            ),
            rename=_normalized_rename(contracts.get("rename", {})),
        ),
        processes=ProcessesSilverSpec(
            identity_key=normalize_name(processes["identity_key"]),
            procedure_key=normalize_name(processes["procedure_key"]),
            reference_key=normalize_name(processes["reference_key"]),
            excluded_semantic_types=tuple(
                str(value) for value in processes.get("excluded_semantic_types", [])
            ),
            rename=_normalized_rename(processes.get("rename", {})),
        ),
        suppliers=SuppliersSilverSpec(
            primary_key=normalize_name(suppliers.get("primary_key", "codigo")),
            nit_key=normalize_name(suppliers.get("nit_key", "nit")),
            excluded_columns=_normalized_values(suppliers.get("excluded_columns", [])),
            excluded_semantic_types=tuple(
                str(value) for value in suppliers.get("excluded_semantic_types", [])
            ),
            rename=_normalized_rename(suppliers.get("rename", {})),
        ),
        bidders=BiddersSilverSpec(
            process_key=normalize_name(bidders.get("process_key", "id_procedimiento")),
            supplier_code_candidate=normalize_name(
                bidders.get("supplier_code_candidate", "codigo_proveedor")
            ),
            nit_candidate=normalize_name(bidders.get("nit_candidate", "nit_proveedor")),
            excluded_columns=_normalized_values(bidders.get("excluded_columns", [])),
            excluded_semantic_types=tuple(
                str(value) for value in bidders.get("excluded_semantic_types", [])
            ),
            rename=_normalized_rename(bidders.get("rename", {})),
        ),
        additions=AdditionsSilverSpec(
            contract_key=normalize_name(additions.get("contract_key", "id_contrato")),
            event_time=normalize_name(additions.get("event_time", "fecharegistro")),
            event_type=normalize_name(additions.get("event_type", "tipo")),
            identifier=normalize_name(additions.get("identifier", "identificador")),
            description=normalize_name(additions.get("description", "descripcion")),
            rename=_normalized_rename(additions.get("rename", {})),
        ),
        entity_resolution=EntityResolutionSpec(
            code_strategy_enabled=bool(entity_resolution.get("code_strategy_enabled", True)),
            nit_strategy_enabled=bool(entity_resolution.get("nit_strategy_enabled", True)),
            report_min_resolved_coverage=float(
                entity_resolution.get("report_min_resolved_coverage", 0.50)
            ),
        ),
        validation=SilverValidationSpec(
            contracts_processes_min_coverage=float(
                validation["contracts_processes_min_coverage"]
            ),
            bidders_processes_min_coverage=float(
                validation.get("bidders_processes_min_coverage", 0.95)
            ),
            additions_contracts_min_coverage=float(
                validation.get("additions_contracts_min_coverage", 0.99)
            ),
            t0_column=normalize_name(validation["t0_column"]),
            t0_min_parse_success_nonnull=float(
                validation["t0_min_parse_success_nonnull"]
            ),
            addition_event_min_parse_success_nonnull=float(
                validation.get("addition_event_min_parse_success_nonnull", 0.99)
            ),
        ),
    )
