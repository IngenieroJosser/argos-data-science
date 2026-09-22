from pathlib import Path

from argos.config.registry import DatasetSpec
from argos.profiling.keys import analyze_candidate_keys


def test_key_analysis_is_not_blocked_by_unrelated_name_collision(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample.csv"
    path.write_text(
        "ID del Proceso,Fecha de emision,Fecha de emisión\n"
        "P1,2025-01-01,2025-01-01\n"
        "P2,2025-01-02,2025-01-02\n",
        encoding="utf-8",
    )

    spec = DatasetSpec(
        key="sample",
        source_id="sample",
        name="Sample",
        match_tokens=("sample",),
        source_url="",
        candidate_keys=(("id_del_proceso",),),
    )

    result = analyze_candidate_keys(
        "sample",
        path,
        spec,
        sample_size=100,
        temp_directory=tmp_path / "duckdb",
    )

    row = result.iloc[0]

    assert row["status"] == "analyzed"
    assert row["raw_columns"] == ["ID del Proceso"]
    assert bool(row["is_unique_when_nonnull"]) is True
