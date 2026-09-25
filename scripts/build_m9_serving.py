from __future__ import annotations

import argparse
from pathlib import Path

from argos.serving.m9 import build_m9_serving


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Construye la capa read-only M9 para el frontend de ARGOS"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Raíz del backend ARGOS",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directorio derivado; por defecto data/serving/m9",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="No reemplazar una base serving existente",
    )
    args = parser.parse_args()

    result = build_m9_serving(
        root=args.root,
        output_dir=args.output_dir,
        overwrite=not args.no_overwrite,
    )
    print("M9 serving ✅ BUILT")
    print(f"batch={result.batch_id}")
    print(f"rows={result.row_count:,}")
    print(f"db={result.database_path}")
    print(f"overview={result.overview_path}")
    print(f"validation={result.validation_path}")
    print("scientific backend mutated: NO")


if __name__ == "__main__":
    main()
