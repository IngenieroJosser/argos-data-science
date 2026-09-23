"""Configuration loaders for ARGOS."""

from argos.config.gold import GoldSpec, load_gold_spec
from argos.config.registry import DatasetSpec, load_registry
from argos.config.silver import SilverSpec, load_silver_spec

__all__ = [
    "DatasetSpec",
    "GoldSpec",
    "SilverSpec",
    "load_registry",
    "load_gold_spec",
    "load_silver_spec",
]
