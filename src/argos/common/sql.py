from __future__ import annotations

from pathlib import Path


def sql_string(value: str | Path) -> str:
    """Return a safely escaped SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def quote_identifier(value: str) -> str:
    """Return a safely quoted SQL identifier for DuckDB."""
    return '"' + value.replace('"', '""') + '"'


def csv_source(
    path: str | Path,
    *,
    sample_size: int = 100_000,
    all_varchar: bool = False,
    null_padding: bool = False,
    parallel: bool = False,
    strict_mode: bool = True,
    ignore_errors: bool = False,
) -> str:
    """Build a conservative DuckDB table expression for a Bronze CSV snapshot.

    SECOP exports can contain quoted multiline text. ARGOS therefore disables
    DuckDB's parallel CSV reader by default. ``null_padding`` is also disabled
    by default: padding malformed/ragged records is a data-quality decision and
    must not be enabled pre-emptively during Bronze auditing.

    The reader is intentionally strict and does not silently skip malformed rows.
    If a source later proves to require a source-specific parsing rule, that rule
    should be documented and configured explicitly rather than hidden globally.
    """
    return (
        "read_csv("
        f"{sql_string(path)}, "
        "header=true, "
        "auto_detect=true, "
        f"sample_size={int(sample_size)}, "
        f"all_varchar={'true' if all_varchar else 'false'}, "
        f"null_padding={'true' if null_padding else 'false'}, "
        f"parallel={'true' if parallel else 'false'}, "
        f"strict_mode={'true' if strict_mode else 'false'}, "
        f"ignore_errors={'true' if ignore_errors else 'false'}"
        ")"
    )


def clean_text_expr(identifier: str) -> str:
    """Return a normalized SQL text expression without mutating Bronze values.

    The expression is intended only for parsing/auditing. The raw source value is
    never overwritten. Common textual null sentinels are treated as absent so they
    do not count as parser failures.
    """
    column = quote_identifier(identifier)
    text = f"NULLIF(TRIM(CAST({column} AS VARCHAR)), '')"
    return (
        "CASE "
        f"WHEN {text} IS NULL THEN NULL "
        f"WHEN LOWER({text}) IN ("
        "'null', 'none', 'nan', 'nat', 'n/a', 'na', "
        "'no definido', 'no definida', 'no aplica'"
        ") THEN NULL "
        f"ELSE {text} END"
    )


def _timestamp_formats(date_order: str = "mdy") -> tuple[tuple[str, str], ...]:
    """Return deterministic timestamp formats in parsing priority order.

    SECOP Socrata CSV exports observed in ARGOS use US-style ``MM/DD/YYYY`` for
    many date columns. ISO formats are attempted first because they are
    unambiguous. The configured local order is attempted next, and the opposite
    slash order is retained only as a fallback for otherwise unparsable values.

    Two-digit-year formats are deliberately excluded: silently guessing a century
    is riskier than reporting an explicit parse failure during Bronze auditing.
    """
    normalized = date_order.lower().strip()
    if normalized not in {"mdy", "dmy"}:
        raise ValueError("date_order must be either 'mdy' or 'dmy'")

    iso = (
        ("iso_tz_fractional", "%Y-%m-%dT%H:%M:%S.%f%z"),
        ("iso_tz", "%Y-%m-%dT%H:%M:%S%z"),
        ("iso_fractional", "%Y-%m-%dT%H:%M:%S.%f"),
        ("iso_datetime", "%Y-%m-%dT%H:%M:%S"),
        ("iso_space_fractional", "%Y-%m-%d %H:%M:%S.%f"),
        ("iso_space_datetime", "%Y-%m-%d %H:%M:%S"),
        ("iso_date", "%Y-%m-%d"),
        ("iso_slash_date", "%Y/%m/%d"),
    )

    mdy = (
        ("mdy_24h_fractional", "%m/%d/%Y %H:%M:%S.%f"),
        ("mdy_24h", "%m/%d/%Y %H:%M:%S"),
        ("mdy_12h", "%m/%d/%Y %I:%M:%S %p"),
        ("mdy_12h_minutes", "%m/%d/%Y %I:%M %p"),
        ("mdy_date", "%m/%d/%Y"),
    )
    dmy = (
        ("dmy_24h_fractional", "%d/%m/%Y %H:%M:%S.%f"),
        ("dmy_24h", "%d/%m/%Y %H:%M:%S"),
        ("dmy_12h", "%d/%m/%Y %I:%M:%S %p"),
        ("dmy_12h_minutes", "%d/%m/%Y %I:%M %p"),
        ("dmy_date", "%d/%m/%Y"),
    )

    local, fallback = (mdy, dmy) if normalized == "mdy" else (dmy, mdy)
    return (*iso, *local, *fallback)


def timestamp_expr(identifier: str, *, date_order: str = "mdy") -> str:
    """Build a deterministic, fault-tolerant timestamp parser for DuckDB.

    This intentionally avoids a leading generic ``TRY_CAST``. Generic casts can
    accept ambiguous representations differently across formats. Bronze temporal
    auditing should instead make the accepted formats explicit and measurable.
    """
    text = clean_text_expr(identifier)
    candidates = [
        f"TRY_STRPTIME({text}, '{format_string}')"
        for _, format_string in _timestamp_formats(date_order)
    ]
    return "COALESCE(" + ", ".join(candidates) + ")"


def timestamp_format_expr(identifier: str, *, date_order: str = "mdy") -> str:
    """Return the label of the first timestamp format that parses a value."""
    text = clean_text_expr(identifier)
    clauses = [
        (
            f"WHEN TRY_STRPTIME({text}, '{format_string}') IS NOT NULL "
            f"THEN '{label}'"
        )
        for label, format_string in _timestamp_formats(date_order)
    ]
    return "CASE WHEN " + text + " IS NULL THEN NULL " + " ".join(clauses) + " ELSE 'unparsed' END"
