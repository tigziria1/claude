"""Agent 1 - Data Ingestion.

Scans the input folder for CSV and Excel files, reads each one robustly
(encoding and delimiter detection, every Excel sheet, row limits, chunked CSV
reads) and returns every table as a pandas DataFrame plus structural metadata.

Values are read as text on purpose: the Data Cleaner needs to see the raw,
messy strings (``"€1,250.00"``, ``"N/A"``) to fix and report them.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import Settings
from agents.common import IngestedDataset, infer_semantic_type, safe_stem, write_json

logger = logging.getLogger("agent.ingestion")

CSV_EXTENSIONS: frozenset[str] = frozenset({".csv", ".tsv", ".txt"})
EXCEL_EXTENSIONS: frozenset[str] = frozenset({".xlsx", ".xlsm", ".xls"})
CANDIDATE_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def detect_encoding(path: Path, sample_size: int = 200_000) -> str:
    """Return the first candidate encoding that decodes the file sample cleanly.

    ``latin-1`` decodes any byte sequence, so it is the guaranteed last resort.
    """
    raw = path.read_bytes()[:sample_size]
    for encoding in CANDIDATE_ENCODINGS:
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin-1"


def detect_delimiter(path: Path, encoding: str) -> str:
    """Sniff the CSV delimiter (``,`` ``;`` tab or ``|``), defaulting to a comma."""
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        sample = handle.read(50_000)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return "\t" if path.suffix.lower() == ".tsv" else ","


def read_csv(path: Path, settings: Settings) -> tuple[pd.DataFrame, str, bool]:
    """Read a CSV file as text columns, in chunks, honouring ``MAX_ROWS_PER_FILE``.

    Returns:
        The DataFrame, the encoding used, and whether rows were truncated.
    """
    encoding = detect_encoding(path)
    delimiter = detect_delimiter(path, encoding)
    logger.debug("%s: encoding=%s delimiter=%r", path.name, encoding, delimiter)

    chunks: list[pd.DataFrame] = []
    row_count = 0
    truncated = False
    reader = pd.read_csv(
        path,
        sep=delimiter,
        encoding=encoding,
        dtype=str,
        keep_default_na=False,
        skip_blank_lines=True,
        on_bad_lines="warn",
        chunksize=max(1, settings.chunk_size_processing),
    )
    with reader:
        for chunk in reader:
            remaining = settings.max_rows_per_file - row_count
            if remaining <= 0:
                truncated = True
                break
            if len(chunk) > remaining:
                chunk = chunk.iloc[:remaining]
                truncated = True
            chunks.append(chunk)
            row_count += len(chunk)
    frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    return frame, encoding, truncated


def read_excel(path: Path, settings: Settings) -> dict[str, tuple[pd.DataFrame, bool]]:
    """Read every non-empty sheet of an Excel workbook as text columns.

    Returns:
        Mapping of sheet name to ``(frame, truncated)``.
    """
    sheets: dict[str, pd.DataFrame] = pd.read_excel(
        path, sheet_name=None, dtype=str, keep_default_na=False, nrows=settings.max_rows_per_file + 1
    )
    result: dict[str, tuple[pd.DataFrame, bool]] = {}
    for sheet_name, frame in sheets.items():
        frame = frame.dropna(how="all")
        if frame.empty:
            logger.info("%s [%s]: empty sheet skipped", path.name, sheet_name)
            continue
        truncated = len(frame) > settings.max_rows_per_file
        result[str(sheet_name)] = (frame.iloc[: settings.max_rows_per_file], truncated)
    return result


def discover_files(settings: Settings, input_path: Path | None = None) -> list[Path]:
    """List the supported data files in the input folder (non-recursive, sorted)."""
    folder = input_path or settings.data_input_path
    if not folder.exists():
        logger.error("Input folder %s does not exist", folder)
        return []
    allowed: set[str] = set()
    if settings.support_csv:
        allowed |= CSV_EXTENSIONS
    if settings.support_excel:
        allowed |= EXCEL_EXTENSIONS
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in allowed and not p.name.startswith(("~$", ".")))
    skipped = sorted(p.name for p in folder.iterdir() if p.is_file() and p not in files and not p.name.startswith("."))
    if skipped:
        logger.info("Skipping unsupported/disabled files: %s", ", ".join(skipped))
    return files


def _build_dataset(name: str, path: Path, frame: pd.DataFrame, encoding: str | None, sheet: str | None, truncated: bool) -> IngestedDataset:
    """Drop fully empty rows/columns and attach inferred types."""
    frame = frame.loc[:, [c for c in frame.columns if not str(c).startswith("Unnamed:") or frame[c].astype(str).str.strip().ne("").any()]]
    frame = frame[~frame.apply(lambda row: all(str(v).strip() == "" for v in row), axis=1)].reset_index(drop=True)
    data_types = {str(col): infer_semantic_type(str(col), frame[col]) for col in frame.columns}
    return IngestedDataset(name=name, source=path.name, path=path, frame=frame, encoding=encoding,
                           sheet=sheet, data_types=data_types, truncated=truncated)


def run(settings: Settings, input_path: Path | None = None) -> list[IngestedDataset]:
    """Agent 1 entry point: ingest every supported file from the input folder.

    A file that fails to load is logged and skipped; it never stops the run.

    Args:
        settings: Loaded configuration.
        input_path: Optional override of ``DATA_INPUT_PATH``.

    Returns:
        One :class:`IngestedDataset` per CSV file / non-empty Excel sheet.
    """
    files = discover_files(settings, input_path)
    logger.info("Found %d data file(s) in %s", len(files), input_path or settings.data_input_path)

    datasets: list[IngestedDataset] = []
    for path in files:
        try:
            if path.suffix.lower() in CSV_EXTENSIONS:
                frame, encoding, truncated = read_csv(path, settings)
                if frame.empty:
                    logger.warning("%s: no rows, skipped", path.name)
                    continue
                datasets.append(_build_dataset(safe_stem(path.stem), path, frame, encoding, None, truncated))
            else:
                sheets = read_excel(path, settings)
                for sheet_name, (frame, truncated) in sheets.items():
                    name = safe_stem(path.stem if len(sheets) == 1 else f"{path.stem}_{sheet_name}")
                    datasets.append(_build_dataset(name, path, frame, None, sheet_name, truncated))
        except Exception:  # one bad file must not break the whole run
            logger.exception("Failed to ingest %s", path.name)
            continue

    for ds in datasets:
        if ds.truncated:
            logger.warning("%s truncated to MAX_ROWS_PER_FILE=%d rows", ds.source, settings.max_rows_per_file)
        logger.info("Ingested %s%s: %d rows x %d columns", ds.source, f" [{ds.sheet}]" if ds.sheet else "",
                    len(ds.frame), len(ds.frame.columns))

    if datasets:
        summary_path = settings.reports_path / f"{datetime.now():%Y-%m-%d}_ingestion_summary.json"
        write_json(summary_path, {"generated_at": datetime.now().isoformat(timespec="seconds"),
                                  "datasets": [d.summary() for d in datasets]})
        logger.info("Ingestion summary saved to %s", summary_path)
    return datasets
