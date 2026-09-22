from pathlib import Path

from argos.profiling.grain import analyze_duplicate_structure


def test_grain_resolution_distinguishes_exact_and_conflicting_duplicates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample.csv"
    path.write_text(
        "id,value\n"
        "A,1\n"
        "A,1\n"
        "B,1\n"
        "B,2\n"
        "C,3\n",
        encoding="utf-8",
    )

    result = analyze_duplicate_structure(
        "sample",
        path,
        ("id",),
        sample_size=100,
        temp_directory=tmp_path / "duckdb",
    )

    assert result["duplicate_key_count"] == 2
    assert result["exact_duplicate_key_count"] == 1
    assert result["conflicting_duplicate_key_count"] == 1
    assert result["grain_interpretation"] == "multiple_payload_variants_per_key"
