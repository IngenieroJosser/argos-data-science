from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.metadata
from pathlib import Path
import platform
import re
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.production import ProductionSpec
from argos.production.audit import append_audit_event
from argos.production.common import read_json, resolve, sha256_file, write_json_atomic

BUILD_IMPLEMENTATION = "m6-50-runtime-registry-v1"


@dataclass(frozen=True, slots=True)
class RegistryResult:
    registry_record: Path
    deployment_state: Path
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _locked_package_version(lockfile: Path, package: str) -> str | None:
    if not lockfile.exists():
        return None
    text = lockfile.read_text(encoding="utf-8", errors="ignore")
    pattern = re.compile(rf'name\s*=\s*"{re.escape(package)}"\s*\nversion\s*=\s*"([^"]+)"', re.I)
    match = pattern.search(text)
    return match.group(1) if match else None


def build_model_registry(
    *,
    root: Path,
    production_spec: ProductionSpec,
    reports_root: Path,
    manifest_dir: Path,
) -> RegistryResult:
    selection_path = resolve(root, production_spec.registry.selection_manifest)
    model_path = resolve(root, production_spec.registry.model_artifact)
    calibrator_path = resolve(root, production_spec.registry.calibrator_artifact)
    model_card = resolve(root, production_spec.registry.model_card)
    robustness_card = resolve(root, production_spec.registry.robustness_card)
    monitoring_spec_path = resolve(root, production_spec.registry.monitoring_spec)
    m5_gate = root / "docs" / "decisions" / "M5_GATE.md"
    for path in [selection_path, model_path, calibrator_path, model_card, robustness_card, monitoring_spec_path, m5_gate]:
        if not path.exists():
            raise FileNotFoundError(path)

    selection = read_json(selection_path)
    model_hash = sha256_file(model_path)
    calibrator_hash = sha256_file(calibrator_path)
    lockfile = resolve(root, production_spec.runtime.lockfile)
    locked_sklearn = _locked_package_version(lockfile, "scikit-learn")
    runtime_sklearn = importlib.metadata.version("scikit-learn")
    python_mm = f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}"

    registry_record = resolve(root, production_spec.registry.registry_record)
    payload: dict[str, Any] = {
        "registry_schema": production_spec.schema_version,
        "model_version": production_spec.core.model_version,
        "stage": production_spec.deployment.default_stage,
        "decision_mode": "human_review_required",
        "scoring_mode": production_spec.core.scoring_mode,
        "model_type": selection.get("selected_model"),
        "calibration_method": selection.get("calibration_method"),
        "model_artifact": str(production_spec.registry.model_artifact),
        "calibrator_artifact": str(production_spec.registry.calibrator_artifact),
        "model_sha256": model_hash,
        "calibrator_sha256": calibrator_hash,
        "selection_sha256": sha256_file(selection_path),
        "feature_registry_sha256": sha256_file(resolve(root, production_spec.data_contract.feature_registry)),
        "model_card_sha256": sha256_file(model_card),
        "robustness_card_sha256": sha256_file(robustness_card),
        "monitoring_spec_sha256": sha256_file(monitoring_spec_path),
        "python_major_minor": python_mm,
        "scikit_learn_runtime": runtime_sklearn,
        "scikit_learn_lock": locked_sklearn,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "production_promotion_authorized": False,
    }
    write_json_atomic(registry_record, payload)

    state_path = resolve(root, production_spec.deployment.state_path)
    if not state_path.exists():
        write_json_atomic(
            state_path,
            {
                "schema_version": production_spec.schema_version,
                "model_version": production_spec.core.model_version,
                "stage": production_spec.deployment.default_stage,
                "previous_stage": None,
                "promotion_blocked": False,
                "block_reason": None,
            },
        )

    records: list[dict[str, Any]] = []
    add_validation(records, check_id="m5_gate_present", category="prerequisite", passed="M5 ✅ CLOSED" in m5_gate.read_text(encoding="utf-8"), observed={"path": str(m5_gate)}, requirement="M6 starts only after the computable M5 gate is closed")
    add_validation(records, check_id="frozen_model_hashes_match_selection", category="lineage", passed=model_hash == str(selection.get("model_sha256")) and calibrator_hash == str(selection.get("calibrator_sha256")), observed={"model": model_hash, "expected_model": selection.get("model_sha256"), "calibrator": calibrator_hash, "expected_calibrator": selection.get("calibrator_sha256")}, requirement="registry points to the exact frozen ARGOS V1 model and calibrator")
    add_validation(records, check_id="runtime_matches_lock", category="runtime", passed=python_mm == production_spec.runtime.python_major_minor and runtime_sklearn == production_spec.runtime.scikit_learn and locked_sklearn == production_spec.runtime.scikit_learn, observed={"python": python_mm, "expected_python": production_spec.runtime.python_major_minor, "sklearn_runtime": runtime_sklearn, "sklearn_lock": locked_sklearn, "expected_sklearn": production_spec.runtime.scikit_learn}, requirement="serialized model runtime is pinned and matches the production contract")
    add_validation(records, check_id="governance_docs_hashed", category="governance", passed=all(payload[k] for k in ["model_card_sha256", "robustness_card_sha256", "monitoring_spec_sha256"]), observed={"model_card": str(model_card), "robustness_card": str(robustness_card), "monitoring_spec": str(monitoring_spec_path)}, requirement="model, robustness and monitoring documentation is part of registry lineage")
    add_validation(records, check_id="production_not_pre_authorized", category="governance", passed=not production_spec.deployment.allow_production_promotion and not payload["production_promotion_authorized"] and production_spec.core.human_review_required, observed={"allow_production_promotion": production_spec.deployment.allow_production_promotion, "human_review_required": production_spec.core.human_review_required}, requirement="M6 package starts batch-first, shadow-only and human-in-the-loop")
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "production" / "50_validation.parquet")

    append_audit_event(root, log_path=production_spec.audit.log_path, event_type="model_registered", actor="argos.system", payload={"model_version": production_spec.core.model_version, "registry_sha256": sha256_file(registry_record), "stage": production_spec.deployment.default_stage})

    manifest_path = write_manifest(
        manifest_dir / "m6_runtime_registry.json",
        {
            "milestone": "M6",
            "component": "50_runtime_and_registry",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": production_spec.schema_version,
            "registry_record": str(registry_record),
            "registry_sha256": sha256_file(registry_record),
            "model_sha256": model_hash,
            "calibrator_sha256": calibrator_hash,
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return RegistryResult(registry_record, state_path, validation, manifest_path)
