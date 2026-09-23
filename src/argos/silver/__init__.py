"""Canonical Silver-layer transformations for ARGOS.

The package avoids importing DuckDB-heavy builders at module-import time. This
keeps configuration, documentation and gate utilities lightweight while
preserving the historical public attributes through lazy loading.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SilverBuildResult",
    "build_contracts_processes_silver",
    "plan_contracts_processes_silver",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from argos.silver.contracts_processes import (
            SilverBuildResult,
            build_contracts_processes_silver,
            plan_contracts_processes_silver,
        )

        return {
            "SilverBuildResult": SilverBuildResult,
            "build_contracts_processes_silver": build_contracts_processes_silver,
            "plan_contracts_processes_silver": plan_contracts_processes_silver,
        }[name]
    raise AttributeError(name)
