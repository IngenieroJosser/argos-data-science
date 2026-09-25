from __future__ import annotations

import json
from pathlib import Path

from argos.common.paths import ProjectPaths
from argos.config.advanced import load_advanced_spec
from argos.config.production import load_production_spec
from argos.config.prospective import load_prospective_spec
from argos.prospective.protocol import verify_frozen_protocol


def gate_status(path: Path, marker: str) -> str:
    if not path.exists():
        return "MISSING"
    return "CLOSED" if marker in path.read_text(encoding="utf-8") else "OPEN"


def main() -> None:
    paths = ProjectPaths.discover()
    advanced = load_advanced_spec(paths.configs / "advanced.toml")
    prospective = load_prospective_spec(paths.configs / "prospective.toml")
    production = load_production_spec(paths.configs / "production.toml")

    print("ARGOS project status")
    print("=" * 72)
    for milestone in range(1, 7):
        gate = paths.docs / "decisions" / f"M{milestone}_GATE.md"
        print(f"M{milestone}: {gate_status(gate, f'M{milestone} ✅ CLOSED')}")

    m7_gate = paths.docs / "decisions" / "M7_GATE.md"
    m7_text = m7_gate.read_text(encoding="utf-8") if m7_gate.exists() else ""
    print(f"M7: {'CLOSED' if 'M7 ✅ CLOSED' in m7_text else 'ACTIVE / EVIDENCE PENDING'}")
    verified, details = verify_frozen_protocol(
        root=paths.root,
        prospective_spec=prospective,
        production_spec=production,
        docs_root=paths.docs,
    )
    print(f"M7 frozen protocol integrity: {'PASS' if verified else 'FAIL'}")
    if not verified:
        print(json.dumps(details, indent=2, ensure_ascii=False, default=str))

    m8_gate = paths.docs / "decisions" / "M8_GATE.md"
    print(f"M8: {gate_status(m8_gate, 'M8 ✅ CLOSED')}")
    print(f"M8 schema: {advanced.schema_version}")

    expected = [
        advanced.artifacts.semantic_manifest,
        advanced.artifacts.graph_manifest,
        advanced.artifacts.anomaly_manifest,
        advanced.artifacts.pit_manifest,
        advanced.artifacts.ablation_manifest,
        advanced.artifacts.selection_manifest,
        advanced.artifacts.survival_outcomes_manifest,
        advanced.artifacts.survival_manifest,
    ]
    missing = [item for item in expected if not (paths.root / item).exists()]
    print(f"M8 manifests: {len(expected) - len(missing)}/{len(expected)} present")
    if missing:
        print("M8 pending artifacts:")
        for item in missing:
            print(f"  - {item}")

    technical_complete = not missing and gate_status(m8_gate, "M8 ✅ CLOSED") == "CLOSED"
    print("-" * 72)
    technical_status = "COMPLETE" if technical_complete else "PENDING M8 RUN"
    print(f"Technical implementation evidence: {technical_status}")
    print(
        "Prospective validation: "
        + ("COMPLETE" if "M7 ✅ CLOSED" in m7_text else "ACTIVE — requires future matured cohorts")
    )


if __name__ == "__main__":
    main()
