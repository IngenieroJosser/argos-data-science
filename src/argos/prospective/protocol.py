from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation
from argos.config.prospective import ProspectiveSpec
from argos.config.production import ProductionSpec
from argos.prospective.common import resolve, sha256_file, write_json_atomic

PROTOCOL_IMPLEMENTATION = "m7-60-protocol-freeze-v2"


@dataclass(frozen=True, slots=True)
class ProtocolFreezeResult:
    validation: pd.DataFrame
    manifest_path: Path
    ready_for_prospective_collection: bool
    status: str


def _canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def protocol_input_paths(
    *, root: Path, production_spec: ProductionSpec, docs_root: Path
) -> dict[str, Path]:
    return {
        "prospective_config": root / "configs" / "prospective.toml",
        "production_config": root / "configs" / "production.toml",
        "selection_manifest": resolve(root, production_spec.registry.selection_manifest),
        "model": resolve(root, production_spec.registry.model_artifact),
        "calibrator": resolve(root, production_spec.registry.calibrator_artifact),
        "scoring_contract": resolve(root, production_spec.data_contract.contract_artifact),
        "model_card": resolve(root, production_spec.registry.model_card),
        "robustness_card": resolve(root, production_spec.registry.robustness_card),
        "monitoring_spec": resolve(root, production_spec.registry.monitoring_spec),
        "m6_gate": docs_root / "decisions" / "M6_GATE.md",
    }


def current_protocol_hashes(
    *, root: Path, production_spec: ProductionSpec, docs_root: Path
) -> tuple[dict[str, str], list[str]]:
    paths = protocol_input_paths(root=root, production_spec=production_spec, docs_root=docs_root)
    missing = [name for name, path in paths.items() if not path.exists()]
    hashes = {name: sha256_file(path) for name, path in paths.items() if path.exists()}
    return hashes, missing


def verify_frozen_protocol(
    *,
    root: Path,
    prospective_spec: ProspectiveSpec,
    production_spec: ProductionSpec,
    docs_root: Path,
) -> tuple[bool, dict[str, Any]]:
    manifest_path = resolve(root, prospective_spec.artifacts.protocol_manifest)
    if not manifest_path.exists():
        return False, {"reason": "missing_protocol_manifest", "path": str(manifest_path)}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    current, missing = current_protocol_hashes(
        root=root, production_spec=production_spec, docs_root=docs_root
    )
    frozen = payload.get("hashes", {})
    mismatches = {
        name: {"frozen": frozen.get(name), "current": current.get(name)}
        for name in sorted(set(frozen) | set(current))
        if frozen.get(name) != current.get(name)
    }
    expected_core = {
        "schema_version": prospective_spec.schema_version,
        "protocol_freeze_date": str(prospective_spec.core.protocol_freeze_date),
        "prospective_start": str(prospective_spec.core.prospective_start),
        "model_version": prospective_spec.core.model_version,
        "target_horizon_days": prospective_spec.core.target_horizon_days,
        "event_type": prospective_spec.outcomes.event_type,
        "operational_fraction": prospective_spec.performance.operational_fraction,
    }
    core_mismatches = {
        key: {"frozen": payload.get(key), "current": value}
        for key, value in expected_core.items()
        if payload.get(key) != value
    }
    ok = not missing and not mismatches and not core_mismatches
    return ok, {
        "path": str(manifest_path),
        "missing_inputs": missing,
        "hash_mismatches": mismatches,
        "core_mismatches": core_mismatches,
        "protocol_id": payload.get("protocol_id"),
    }


def freeze_m7_protocol(
    *,
    root: Path,
    prospective_spec: ProspectiveSpec,
    production_spec: ProductionSpec,
    reports_root: Path,
    docs_root: Path,
) -> ProtocolFreezeResult:
    records: list[dict[str, Any]] = []
    m6_gate = docs_root / "decisions" / "M6_GATE.md"
    m6_closed = m6_gate.exists() and "M6 ✅ CLOSED" in m6_gate.read_text(encoding="utf-8")
    add_validation(
        records,
        check_id="m6_closed_prerequisite",
        category="prerequisite",
        passed=m6_closed,
        observed={"path": str(m6_gate)},
        requirement="M7 starts only after formal M6 closure",
    )

    add_validation(
        records,
        check_id="prospective_start_after_freeze",
        category="temporal_governance",
        passed=prospective_spec.core.prospective_start > prospective_spec.core.protocol_freeze_date,
        observed={
            "freeze": str(prospective_spec.core.protocol_freeze_date),
            "start": str(prospective_spec.core.prospective_start),
        },
        requirement="all M7 evaluation cohorts occur strictly after protocol freeze",
    )

    add_validation(
        records,
        check_id="consumed_holdouts_locked",
        category="evaluation_governance",
        passed=not prospective_spec.governance.allow_reuse_consumed_holdouts_for_selection,
        observed={
            "test_year": prospective_spec.governance.consumed_test_year,
            "oot_year": prospective_spec.governance.consumed_oot_year,
        },
        requirement="TEST 2025 and OOT 2026 stay consumed and cannot drive M7 selection/tuning",
    )

    add_validation(
        records,
        check_id="human_review_preserved",
        category="governance",
        passed=(
            prospective_spec.governance.human_review_required
            and production_spec.core.human_review_required
        ),
        observed={
            "m7": prospective_spec.governance.human_review_required,
            "m6": production_spec.core.human_review_required,
        },
        requirement="M7 remains human-in-the-loop",
    )

    add_validation(
        records,
        check_id="automatic_promotion_disabled",
        category="governance",
        passed=(
            not prospective_spec.governance.automatic_production_promotion
            and not production_spec.deployment.allow_production_promotion
        ),
        observed={
            "m7_auto_promotion": prospective_spec.governance.automatic_production_promotion,
            "m6_production_promotion": production_spec.deployment.allow_production_promotion,
        },
        requirement="prospective evidence cannot trigger automatic production promotion",
    )

    hashes, missing = current_protocol_hashes(
        root=root, production_spec=production_spec, docs_root=docs_root
    )
    add_validation(
        records,
        check_id="protocol_inputs_present",
        category="lineage",
        passed=not missing,
        observed={"missing": missing},
        requirement="all protocol inputs and frozen model assets are present",
    )

    immutable_core: dict[str, Any] = {
        "schema_version": prospective_spec.schema_version,
        "implementation": PROTOCOL_IMPLEMENTATION,
        "protocol_freeze_date": str(prospective_spec.core.protocol_freeze_date),
        "prospective_start": str(prospective_spec.core.prospective_start),
        "model_version": prospective_spec.core.model_version,
        "target_horizon_days": prospective_spec.core.target_horizon_days,
        "event_type": prospective_spec.outcomes.event_type,
        "operational_fraction": prospective_spec.performance.operational_fraction,
        "outcome_reporting_lag_days": prospective_spec.cohorts.outcome_reporting_lag_days,
        "consumed_holdouts": [
            prospective_spec.governance.consumed_test_year,
            prospective_spec.governance.consumed_oot_year,
        ],
        "hashes": hashes,
        "automatic_production_promotion": False,
        "human_review_required": True,
    }
    protocol_id = _canonical_hash(immutable_core)
    manifest_path = resolve(root, prospective_spec.artifacts.protocol_manifest)

    status = "created"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing_core = {k: existing.get(k) for k in immutable_core}
        same = existing_core == immutable_core and existing.get("protocol_id") == protocol_id
        status = "preserved" if same else "conflict"
        add_validation(
            records,
            check_id="protocol_manifest_immutable",
            category="lineage",
            passed=same,
            observed={"path": str(manifest_path), "status": status},
            requirement="an existing protocol freeze is never silently overwritten",
        )
    else:
        payload = {
            **immutable_core,
            "protocol_id": protocol_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        write_json_atomic(manifest_path, payload)
        add_validation(
            records,
            check_id="protocol_manifest_immutable",
            category="lineage",
            passed=True,
            observed={"path": str(manifest_path), "status": status},
            requirement="protocol freeze is persisted once and subsequently treated as immutable",
        )

    verified, details = verify_frozen_protocol(
        root=root,
        prospective_spec=prospective_spec,
        production_spec=production_spec,
        docs_root=docs_root,
    )
    add_validation(
        records,
        check_id="protocol_manifest_verified",
        category="lineage",
        passed=verified,
        observed=details,
        requirement="frozen M7 hashes still match the exact V1 assets and governance inputs",
    )

    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "prospective" / "60_validation.parquet")
    blocking = validation.loc[validation["blocking"]]
    ready = bool(not blocking.empty and blocking["passed"].all())
    return ProtocolFreezeResult(validation, manifest_path, ready, status)
