"""Shared data structures and parsing helpers used by the four agents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Strings that real-world exports use to mean "no value".
NULL_TOKENS: frozenset[str] = frozenset({
    "", "na", "n/a", "nan", "null", "none", "nil", "-", "--", "?", "#n/a", "missing", "undefined",
})

# Keywords that identify money / headline amount columns.
AMOUNT_KEYWORDS: tuple[str, ...] = ("revenue", "sales", "amount", "total", "price", "cost", "value", "income", "profit")
ID_PATTERN = re.compile(r"(^id$|id$|_id$|^id_|identifier|uuid|reference|^ref)", re.IGNORECASE)
DATE_KEYWORDS: tuple[str, ...] = ("date", "time", "day", "month", "created", "updated", "timestamp", "period")

_CURRENCY_PATTERN = re.compile(r"(€|\$|£|¥|eur|usd|gbp|chf|mad|dzd)", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}(:\d{2})?)?$")


@dataclass
class IngestedDataset:
    """Output of Agent 1: one raw table plus its structural metadata."""

    name: str
    source: str
    path: Path
    frame: pd.DataFrame
    encoding: str | None = None
    sheet: str | None = None
    data_types: dict[str, str] = field(default_factory=dict)
    truncated: bool = False

    def summary(self) -> dict[str, Any]:
        """JSON-serialisable description matching the CLAUDE.md example output."""
        return {
            "name": self.name,
            "source": self.source,
            "sheet": self.sheet,
            "encoding": self.encoding,
            "rows": int(len(self.frame)),
            "columns": [str(c) for c in self.frame.columns],
            "data_types": self.data_types,
            "truncated": self.truncated,
        }


@dataclass
class CleanedDataset:
    """Output of Agent 2: a clean table, its column profile and the cleaning report."""

    name: str
    source: str
    frame: pd.DataFrame
    report: dict[str, Any]
    profile: dict[str, Any]
    cleaned_path: Path | None = None
    report_path: Path | None = None


@dataclass
class AnalysisResult:
    """Output of Agent 3: computed statistics plus the narrative insights."""

    name: str
    source: str
    stats: dict[str, Any]
    insights: dict[str, Any]
    engine: str  # "claude" or "statistical"
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def to_camel_case(name: Any) -> str:
    """Convert an arbitrary column header to camelCase (``" Order ID"`` -> ``orderId``)."""
    text = re.sub(r"\(.*?\)", " ", str(name))  # drop units like "(EUR)"
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return "column"
    # Split existing camelCase / PascalCase words while keeping acronyms intact.
    parts: list[str] = []
    for word in words:
        parts.extend(re.findall(r"[A-Z]+(?=[A-Z][a-z]|\b|\d)|[A-Z]?[a-z]+|[A-Z]+|\d+", word) or [word])
    head, *tail = [p.lower() for p in parts]
    result = head + "".join(p.capitalize() for p in tail)
    return result if not result[0].isdigit() else f"col{result}"


def is_null_token(value: Any) -> bool:
    """True if ``value`` is a missing value or a textual null placeholder."""
    if value is None:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    if value is pd.NaT or value is pd.NA:
        return True
    return isinstance(value, str) and value.strip().lower() in NULL_TOKENS


def parse_number(value: Any) -> float | None:
    """Parse a messy numeric string (``"€1,250.00"``, ``"1.250,5 EUR"``, ``" 42 "``).

    Returns ``None`` when the value cannot be interpreted as a number.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        return float(value)
    text = _CURRENCY_PATTERN.sub("", str(value)).replace(" ", "").replace(" ", "").strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    percent = text.endswith("%")
    text = text.rstrip("%")
    if "," in text and "." in text:
        # Whichever separator comes last is the decimal separator.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+", text):
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    if not _NUMBER_PATTERN.match(text):
        return None
    number = float(text)
    if percent:
        number /= 100
    return -number if negative else number


CURRENCY_CODES: dict[str, str] = {"€": "EUR", "eur": "EUR", "$": "USD", "usd": "USD", "£": "GBP", "gbp": "GBP",
                                  "¥": "JPY", "chf": "CHF", "mad": "MAD", "dzd": "DZD"}


def currency_codes(values: pd.Series) -> set[str]:
    """Set of currency codes whose symbols appear in a column's raw values."""
    found = values.dropna().astype(str).str.extract(_CURRENCY_PATTERN, expand=False).dropna().str.lower()
    return set(found.map(CURRENCY_CODES).dropna())


def detect_currency(header: str, values: pd.Series) -> str | None:
    """Detect the currency of a money column from its header or its raw values."""
    for token in re.findall(r"[A-Za-z€$£¥]+", str(header)):
        if token.lower() in CURRENCY_CODES:
            return CURRENCY_CODES[token.lower()]
    found = values.dropna().astype(str).str.extract(_CURRENCY_PATTERN, expand=False).dropna().str.lower()
    if found.empty:
        return None
    codes = found.map(CURRENCY_CODES).value_counts()
    return str(codes.index[0])


def is_clean_number_string(value: Any) -> bool:
    """True if ``value`` is already a plain machine-readable number."""
    if isinstance(value, (int, float, np.integer, np.floating)):
        return True
    return isinstance(value, str) and bool(_NUMBER_PATTERN.match(value.strip())) and value == value.strip()


def is_iso_date_string(value: Any) -> bool:
    """True if ``value`` is already an ISO-8601 date string or a datetime object."""
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return True
    return isinstance(value, str) and bool(_ISO_DATE_PATTERN.match(value))


def parse_dates(series: pd.Series) -> pd.Series:
    """Parse a column holding mixed date formats into ``datetime64`` (NaT if invalid)."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    text = series.astype("string").str.strip()
    return pd.to_datetime(text, format="mixed", errors="coerce")


def numeric_ratio(series: pd.Series) -> float:
    """Share of non-null values in ``series`` that parse as numbers."""
    values = [v for v in series.tolist() if not is_null_token(v)]
    if not values:
        return 0.0
    sample = values[:2000]
    return sum(parse_number(v) is not None for v in sample) / len(sample)


def date_ratio(series: pd.Series) -> float:
    """Share of non-null values in ``series`` that parse as dates (pure numbers excluded)."""
    values = [v for v in series.tolist() if not is_null_token(v)]
    if not values:
        return 0.0
    sample = pd.Series(values[:2000])
    if pd.api.types.is_datetime64_any_dtype(sample):
        return 1.0
    as_text = sample.astype(str)
    # Bare numbers ("2024", "15") are numeric data, not dates.
    looks_textual = ~as_text.str.strip().str.fullmatch(r"[+-]?[\d.,]+")
    parsed = pd.to_datetime(as_text.where(looks_textual), format="mixed", errors="coerce")
    return float(parsed.notna().mean())


def infer_semantic_type(name: str, series: pd.Series) -> str:
    """Guess the logical type of a raw column: ``numeric``, ``datetime``, ``boolean`` or ``text``."""
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    lowered = str(name).lower()
    non_null = [v for v in series.tolist() if not is_null_token(v)]
    if non_null and {str(v).strip().lower() for v in non_null} <= {"true", "false", "yes", "no", "y", "n"}:
        return "boolean"
    if any(k in lowered for k in DATE_KEYWORDS) and date_ratio(series) >= 0.8:
        return "datetime"
    if numeric_ratio(series) >= 0.9:
        return "numeric"
    if date_ratio(series) >= 0.9:
        return "datetime"
    return "text"


def json_default(value: Any) -> Any:
    """``json.dumps`` fallback for numpy / pandas / pathlib objects."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    if value is pd.NaT or value is pd.NA:
        return None
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serialisable")


def write_json(path: Path, payload: Any) -> Path:
    """Write ``payload`` as pretty UTF-8 JSON and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=json_default), encoding="utf-8")
    return path


def safe_stem(text: str) -> str:
    """Make a filesystem-safe slug from a dataset name."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    return slug or "dataset"
