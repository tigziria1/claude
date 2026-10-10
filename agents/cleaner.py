"""Agent 2 - Data Cleaner.

Turns chaotic tables into analysis-ready data and documents every fix:

1. Unify column names to camelCase.
2. Normalise null placeholders (``"N/A"``, ``"-"``, ``"null"``...) and trim whitespace.
3. Convert numeric text (``"€1,250.00"``, ``"1250 EUR"``) to numbers.
4. Convert mixed date formats to ISO dates.
5. Standardise category labels that differ only by case/spacing.
6. Remove duplicate rows.
7. Repair missing values: first from arithmetic relationships between columns
   (e.g. ``revenue = quantity x unitPrice``), then median / ``"Unknown"``.
8. Flag outliers (z-score) and rows that break a detected relationship.
9. Categorise columns (id, date, amount, measure, category, text) and suggest groupings.
10. Score data quality before and after.
"""

from __future__ import annotations

import logging
from datetime import datetime
from itertools import permutations
from typing import Any

import numpy as np
import pandas as pd

from config import Settings
from agents.common import (
    AMOUNT_KEYWORDS,
    ID_PATTERN,
    CleanedDataset,
    IngestedDataset,
    currency_codes,
    detect_currency,
    infer_semantic_type,
    is_clean_number_string,
    is_iso_date_string,
    is_null_token,
    parse_dates,
    parse_number,
    to_camel_case,
    write_json,
)

logger = logging.getLogger("agent.cleaner")

UNKNOWN_LABEL = "Unknown"
FLAG_COLUMN = "qualityFlag"
MAX_CATEGORY_CARDINALITY = 50


def _unique_names(names: list[str]) -> list[str]:
    """Make column names unique by suffixing repeats (``value``, ``value2``...)."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        count = seen.get(name, 0) + 1
        seen[name] = count
        result.append(name if count == 1 else f"{name}{count}")
    return result


def quality_score(frame: pd.DataFrame, types: dict[str, str], raw: bool) -> dict[str, float]:
    """Score a table on completeness, validity and uniqueness (each 0-1).

    Args:
        frame: Table to score.
        types: Logical type per column (``numeric``, ``datetime``, ``text``...).
        raw: True for the raw text table (validity checks the textual format),
            False for the cleaned table (validity checks typed values).

    Returns:
        The three components plus ``overall`` (weighted 40/30/30).
    """
    if frame.empty:
        return {"completeness": 0.0, "validity": 0.0, "uniqueness": 0.0, "overall": 0.0}
    columns = [c for c in frame.columns if c != FLAG_COLUMN]
    cells = frame[columns]
    null_mask = cells.map(is_null_token)
    completeness = 1 - null_mask.to_numpy().mean()

    valid = 0
    checked = 0
    for col in columns:
        kind = types.get(col, "text")
        values = cells.loc[~null_mask[col], col]
        if values.empty:
            continue
        checked += len(values)
        if kind == "numeric":
            valid += int(values.map(is_clean_number_string).sum()) if raw else len(values)
        elif kind == "datetime":
            valid += int(values.map(is_iso_date_string).sum())
        else:
            as_text = values.astype(str)
            stripped = as_text.str.strip()
            canonical = stripped.str.casefold().map(stripped.groupby(stripped.str.casefold()).agg(lambda s: s.mode().iat[0]))
            valid += int(((as_text == stripped) & (stripped == canonical)).sum())
    validity = valid / checked if checked else 1.0

    duplicates = int(cells.astype(str).duplicated().sum())
    uniqueness = 1 - duplicates / len(cells)
    overall = 0.4 * completeness + 0.3 * validity + 0.3 * uniqueness
    return {k: round(float(v), 4) for k, v in
            {"completeness": completeness, "validity": validity, "uniqueness": uniqueness, "overall": overall}.items()}


def _find_product_relationships(frame: pd.DataFrame, numeric_cols: list[str]) -> list[tuple[str, str, str]]:
    """Detect ``c = a * b`` relationships that hold for >= 90 % of complete rows."""
    relationships: list[tuple[str, str, str]] = []
    for a, b, c in permutations(numeric_cols, 3):
        if a > b:  # a*b is symmetric: test each pair once
            continue
        complete = frame[[a, b, c]].dropna()
        if len(complete) < 10:
            continue
        expected = complete[a] * complete[b]
        matches = np.isclose(complete[c], expected, rtol=0.01, atol=0.01)
        if matches.mean() >= 0.9:
            relationships.append((a, b, c))
    return relationships


def _classify_columns(frame: pd.DataFrame, types: dict[str, str]) -> dict[str, Any]:
    """Assign a role to every column and pick the key columns for analysis."""
    roles: dict[str, str] = {}
    rows = max(len(frame), 1)
    for col in frame.columns:
        if col == FLAG_COLUMN:
            continue
        kind = types.get(col, "text")
        lowered = col.lower()
        unique = frame[col].nunique(dropna=True)
        if kind == "datetime":
            roles[col] = "date"
        elif ID_PATTERN.search(col) and (kind == "text" or unique / rows > 0.9):
            roles[col] = "id"
        elif kind == "numeric":
            roles[col] = "amount" if any(k in lowered for k in AMOUNT_KEYWORDS) else "measure"
        elif kind == "boolean":
            roles[col] = "category"
        elif unique / rows > 0.9 and unique > 20:
            roles[col] = "id"
        elif unique <= MAX_CATEGORY_CARDINALITY:
            roles[col] = "category"
        else:
            roles[col] = "text"

    dates = [c for c, r in roles.items() if r == "date"]
    amounts = [c for c, r in roles.items() if r == "amount"]
    measures = [c for c, r in roles.items() if r == "measure"]

    def amount_rank(col: str) -> tuple[int, float]:
        priority = next((i for i, k in enumerate(("revenue", "sales", "amount", "total", "profit", "value", "income"))
                         if k in col.lower()), 99)
        return priority, -float(frame[col].abs().sum())

    primary_amount = sorted(amounts, key=amount_rank)[0] if amounts else (
        max(measures, key=lambda c: float(frame[c].abs().sum())) if measures else None)
    primary_date = max(dates, key=lambda c: frame[c].notna().sum()) if dates else None
    dimensions = sorted(
        (c for c, r in roles.items() if r == "category" and 2 <= frame[c].nunique() <= MAX_CATEGORY_CARDINALITY),
        key=lambda c: frame[c].nunique(),
    )
    groupings = [f"{primary_amount} by {d}" for d in dimensions] if primary_amount else []
    if primary_amount and primary_date:
        groupings.insert(0, f"{primary_amount} by month ({primary_date})")
    return {
        "column_roles": roles,
        "numeric_columns": [c for c in roles if types.get(c) == "numeric"],
        "text_columns": [c for c in roles if types.get(c) == "text"],
        "key_columns": {
            "id": [c for c, r in roles.items() if r == "id"],
            "dates": dates,
            "amounts": amounts,
            "primary_date": primary_date,
            "primary_amount": primary_amount,
            "dimensions": dimensions,
        },
        "suggested_groupings": groupings,
    }


def clean_dataset(dataset: IngestedDataset, settings: Settings) -> CleanedDataset:
    """Clean one ingested table and build its cleaning report.

    Args:
        dataset: Raw table from Agent 1.
        settings: Cleaning switches (``AUTO_FIX_NULLS``, ``OUTLIER_THRESHOLD``...).

    Returns:
        The cleaned table, its column profile and a JSON-ready report.
    """
    raw = dataset.frame.copy()
    rows_before = len(raw)
    fixes: dict[str, int] = {
        "duplicates_removed": 0,
        "null_values_filled": 0,
        "values_derived_from_relationships": 0,
        "null_placeholders_normalized": 0,
        "whitespace_trimmed": 0,
        "numbers_reformatted": 0,
        "dates_standardized": 0,
        "labels_standardized": 0,
        "format_errors_fixed": 0,
        "outliers_flagged": 0,
        "inconsistent_rows_flagged": 0,
        "unparseable_values_nulled": 0,
    }
    actions: list[str] = []
    warnings: list[str] = []

    # 1. Column names -> camelCase
    original_columns = [str(c) for c in raw.columns]
    new_columns = _unique_names([to_camel_case(c) for c in original_columns])
    renamed = {o: n for o, n in zip(original_columns, new_columns) if o != n}
    raw.columns = new_columns
    df = raw.astype(object)
    raw_types = {new: dataset.data_types.get(old, infer_semantic_type(new, df[new])) for old, new in zip(original_columns, new_columns)}
    if renamed:
        actions.append(f"Renamed {len(renamed)} column(s) to camelCase")
    quality_before = quality_score(df, raw_types, raw=True)
    currencies = {new: cur for old, new in zip(original_columns, new_columns)
                  if raw_types[new] == "numeric" and (cur := detect_currency(old, df[new]))}
    mixed_currency_columns = sorted(c for c in currencies if len(currency_codes(df[c])) > 1)

    # 2. Null placeholders and whitespace
    for col in df.columns:
        series = df[col]
        is_text = series.map(lambda v: isinstance(v, str))
        placeholders = series.map(lambda v: isinstance(v, str) and is_null_token(v) and v != "")
        fixes["null_placeholders_normalized"] += int(placeholders.sum())
        stripped = series.where(~is_text, series.astype(str).str.strip())
        fixes["whitespace_trimmed"] += int((is_text & (stripped != series) & ~placeholders).sum())
        df[col] = stripped.map(lambda v: np.nan if is_null_token(v) else v)

    types: dict[str, str] = {}
    for col in df.columns:
        kind = raw_types[col]
        non_null = df[col].notna()
        # 3. Numbers
        if kind == "numeric":
            parsed = df[col].map(parse_number)
            reformatted = non_null & ~df[col].map(is_clean_number_string)
            unparseable = non_null & parsed.isna()
            fixes["numbers_reformatted"] += int((reformatted & ~unparseable).sum())
            fixes["unparseable_values_nulled"] += int(unparseable.sum())
            df[col] = pd.to_numeric(parsed, errors="coerce").astype(float)
        # 4. Dates
        elif kind == "datetime":
            parsed = parse_dates(df[col])
            changed = non_null & ~df[col].map(is_iso_date_string)
            unparseable = non_null & parsed.isna()
            fixes["dates_standardized"] += int((changed & ~unparseable).sum())
            fixes["unparseable_values_nulled"] += int(unparseable.sum())
            df[col] = parsed
        # 5. Category labels
        elif kind in ("text", "boolean"):
            values = df[col].dropna().astype(str)
            keys = values.str.casefold()
            if 0 < keys.nunique() <= max(MAX_CATEGORY_CARDINALITY, len(values) // 20):
                canonical = values.groupby(keys).agg(lambda s: s.value_counts().index[0])
                standardized = df[col].map(lambda v: canonical.get(str(v).casefold(), v) if isinstance(v, str) else v)
                fixes["labels_standardized"] += int((standardized.notna() & (standardized != df[col])).sum())
                df[col] = standardized
        types[col] = kind
    fixes["format_errors_fixed"] = (fixes["numbers_reformatted"] + fixes["dates_standardized"]
                                    + fixes["labels_standardized"] + fixes["whitespace_trimmed"])
    actions.append(f"Fixed {fixes['format_errors_fixed']} formatting issue(s) (numbers, dates, labels, whitespace)")

    # 6. Duplicates
    if settings.auto_remove_duplicates:
        duplicated = df.duplicated(keep="first")
        fixes["duplicates_removed"] = int(duplicated.sum())
        df = df.loc[~duplicated].reset_index(drop=True)
        if fixes["duplicates_removed"]:
            actions.append(f"Removed {fixes['duplicates_removed']} duplicate row(s)")

    profile = _classify_columns(df, types)
    profile["currencies"] = currencies
    for col in mixed_currency_columns:
        warnings.append(f"Column '{col}' mixes currencies; values were NOT converted - totals may be misleading")
    id_columns = profile["key_columns"]["id"]
    for col in id_columns:
        repeated = int(df[col].dropna().duplicated().sum())
        if repeated:
            warnings.append(f"Column '{col}' looks like an identifier but has {repeated} repeated value(s) with different data")

    # 7. Missing values
    numeric_cols = [c for c in df.columns if types.get(c) == "numeric"]
    relationships = _find_product_relationships(df, numeric_cols)
    for a, b, c in relationships:
        actions.append(f"Detected relationship {c} = {a} x {b}")
    missing_before = {c: int(df[c].isna().sum()) for c in df.columns}

    if settings.auto_fix_nulls:
        for a, b, c in relationships:
            masks = {
                c: df[c].isna() & df[a].notna() & df[b].notna(),
                a: df[a].isna() & df[b].notna() & df[c].notna() & (df[b] != 0),
                b: df[b].isna() & df[a].notna() & df[c].notna() & (df[a] != 0),
            }
            df.loc[masks[c], c] = df.loc[masks[c], a] * df.loc[masks[c], b]
            df.loc[masks[a], a] = df.loc[masks[a], c] / df.loc[masks[a], b]
            df.loc[masks[b], b] = df.loc[masks[b], c] / df.loc[masks[b], a]
            for col in (a, b, c):
                observed = df.loc[~masks[col], col].dropna()
                if masks[col].any() and len(observed) and np.allclose(observed, observed.round()):
                    df.loc[masks[col], col] = df.loc[masks[col], col].round()  # keep counts integral
            fixes["values_derived_from_relationships"] += int(sum(m.sum() for m in masks.values()))

        for col in df.columns:
            missing = df[col].isna()
            if not missing.any():
                continue
            kind = types.get(col)
            role = profile["column_roles"].get(col)
            if kind == "numeric":
                observed = df.loc[~missing, col]
                integer_like = bool(len(observed)) and bool(np.allclose(observed, observed.round()))
                fill = float(observed.median()) if len(observed) else 0.0
                df.loc[missing, col] = round(fill) if integer_like else round(fill, 2)
            elif kind in ("text", "boolean") and role != "id":
                df.loc[missing, col] = UNKNOWN_LABEL
            else:
                continue  # dates and identifiers cannot be imputed reliably
            fixes["null_values_filled"] += int(missing.sum())

        for col in numeric_cols:
            values = df[col].dropna()
            if len(values) and np.allclose(values, values.round()):
                df[col] = df[col].round().astype("Int64")
        if fixes["values_derived_from_relationships"]:
            actions.append(f"Derived {fixes['values_derived_from_relationships']} missing value(s) from column relationships")
        if fixes["null_values_filled"]:
            actions.append(f"Filled {fixes['null_values_filled']} missing value(s) (median for numbers, '{UNKNOWN_LABEL}' for labels)")

    for col in df.columns:
        remaining = int(df[col].isna().sum())
        if remaining and types.get(col) == "datetime":
            warnings.append(f"{remaining} row(s) have no valid '{col}' and are excluded from time-based analysis")
        elif remaining:
            warnings.append(f"{remaining} missing value(s) left in '{col}'")

    # 8. Outliers and inconsistent rows
    flags = pd.Series("", index=df.index, dtype=object)
    if settings.auto_detect_outliers:
        for a, b, c in relationships:
            complete = df[[a, b, c]].notna().all(axis=1)
            product = df[a].astype(float) * df[b].astype(float)
            broken = complete & ~np.isclose(df[c].astype(float), product, rtol=0.01, atol=0.01)
            flags[broken] = "inconsistent"
            fixes["inconsistent_rows_flagged"] += int(broken.sum())
        for col in numeric_cols:
            if col in id_columns:
                continue
            values = df[col].astype(float)
            if (values.dropna() > 0).all() and values.skew() > 1:
                values = np.log(values)  # right-skewed money/volume data: judge outliers on a log scale
            std = values.std()
            if not std or np.isnan(std):
                continue
            z = (values - values.mean()) / std
            outlier = z.abs() > settings.outlier_threshold
            new = outlier & (flags == "")
            flags[new] = "outlier"
            fixes["outliers_flagged"] += int(outlier.sum())
        df[FLAG_COLUMN] = flags
        if fixes["outliers_flagged"] or fixes["inconsistent_rows_flagged"]:
            actions.append(f"Flagged {fixes['outliers_flagged']} outlier value(s) and "
                           f"{fixes['inconsistent_rows_flagged']} inconsistent row(s) in '{FLAG_COLUMN}' (kept, not deleted)")

    primary_date = profile["key_columns"]["primary_date"]
    if primary_date:
        df = df.sort_values(primary_date, kind="stable", na_position="last").reset_index(drop=True)

    quality_after = quality_score(df, types, raw=False)
    report = {
        "dataset": dataset.name,
        "source": dataset.source,
        "sheet": dataset.sheet,
        "cleaned": True,
        "cleaned_at": datetime.now().isoformat(timespec="seconds"),
        "rows_before": rows_before,
        "rows_after": int(len(df)),
        "columns_renamed": renamed,
        "column_types": types,
        "missing_values_before_imputation": {k: v for k, v in missing_before.items() if v},
        "relationships": [f"{c} = {a} x {b}" for a, b, c in relationships],
        "issues_fixed": fixes,
        "actions": actions,
        "warnings": warnings,
        "quality_before": quality_before,
        "quality_after": quality_after,
        "quality_score": quality_after["overall"],
        "profile": profile,
    }
    return CleanedDataset(name=dataset.name, source=dataset.source, frame=df, report=report, profile=profile)


def _export_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Format dates as ISO strings for CSV export."""
    out = frame.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            has_time = (out[col].dropna().dt.normalize() != out[col].dropna()).any()
            out[col] = out[col].dt.strftime("%Y-%m-%dT%H:%M:%S" if has_time else "%Y-%m-%d")
    return out


def run(datasets: list[IngestedDataset], settings: Settings) -> list[CleanedDataset]:
    """Agent 2 entry point: clean every dataset and save the results.

    Saves ``<name>_cleaned.csv`` to ``DATA_OUTPUT_PATH`` and, when
    ``SAVE_CLEANING_REPORT`` is on, ``cleaning_report_<date>_<name>.json`` to
    ``REPORTS_PATH``. A dataset that fails to clean is logged and skipped.
    """
    cleaned: list[CleanedDataset] = []
    stamp = f"{datetime.now():%Y-%m-%d}"
    for dataset in datasets:
        try:
            result = clean_dataset(dataset, settings)
        except Exception:
            logger.exception("Failed to clean %s", dataset.name)
            continue

        result.cleaned_path = settings.data_output_path / f"{dataset.name}_cleaned.csv"
        result.cleaned_path.parent.mkdir(parents=True, exist_ok=True)
        _export_frame(result.frame).to_csv(result.cleaned_path, index=False, encoding="utf-8")
        if settings.save_cleaning_report:
            result.report_path = write_json(settings.reports_path / f"cleaning_report_{stamp}_{dataset.name}.json", result.report)

        r = result.report
        logger.info("Cleaned %s: %d -> %d rows | duplicates=%d nulls_filled=%d derived=%d format_fixes=%d outliers=%d | quality %.0f%% -> %.0f%%",
                    dataset.name, r["rows_before"], r["rows_after"], r["issues_fixed"]["duplicates_removed"],
                    r["issues_fixed"]["null_values_filled"], r["issues_fixed"]["values_derived_from_relationships"],
                    r["issues_fixed"]["format_errors_fixed"], r["issues_fixed"]["outliers_flagged"],
                    100 * r["quality_before"]["overall"], 100 * r["quality_after"]["overall"])
        for warning in r["warnings"]:
            logger.warning("%s: %s", dataset.name, warning)
        cleaned.append(result)
    return cleaned
