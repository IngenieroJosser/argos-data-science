"""Read-only serving layer for the ARGOS analytical frontend."""

from argos.serving.m9 import (
    M9_SCHEMA_VERSION,
    ServingBuildResult,
    build_m9_serving,
)

__all__ = ["M9_SCHEMA_VERSION", "ServingBuildResult", "build_m9_serving"]
