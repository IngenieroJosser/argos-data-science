from pathlib import Path

from argos.common.csv import inspect_csv_snapshot


def test_inspect_csv_snapshot_counts_multiline_logical_rows(tmp_path: Path) -> None:
    path = tmp_path / "sample.csv"
    path.write_text(
        'id,description,value\n'
        '1,"first line\nsecond line",10\n'
        '2,"normal",20\n',
        encoding="utf-8",
    )

    stats = inspect_csv_snapshot(path)

    assert stats.row_count == 2
    assert stats.column_count == 3
    assert stats.ragged_row_count == 0


def test_inspect_csv_snapshot_reports_ragged_rows(tmp_path: Path) -> None:
    path = tmp_path / "sample.csv"
    path.write_text("a,b,c\n1,2,3\n4,5\n", encoding="utf-8")

    stats = inspect_csv_snapshot(path)

    assert stats.row_count == 2
    assert stats.column_count == 3
    assert stats.ragged_row_count == 1
    assert stats.min_fields == 2
    assert stats.max_fields == 3
